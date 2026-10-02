import asyncio
import json
from collections.abc import Awaitable
from typing import Any, TypeVar

import httpx
import pytest
import websockets
import websockets.exceptions

from schwab_mcp.approvals import (
    ApprovalDecision,
    ApprovalRequest,
    SignalApprovalManager,
    SignalApprovalSettings,
    signal as signal_mod,
)
from schwab_mcp.tools._registration import _format_argument

T = TypeVar("T")

_BOT_ACCOUNT = "+15555550100"
_APPROVER = "+15555550199"
_FULL_HASH = "0123456789ABCDEF5805"


def await_result(awaitable: Awaitable[T]) -> T:
    async def _runner() -> T:
        return await awaitable

    return asyncio.run(_runner())


def _cancel_args(order_id: str = "1006299986057", account_hash: str = _FULL_HASH) -> dict[str, str]:
    """Arguments exactly as the auto-wrap in tools/_registration.py produces
    them: each value repr()-encoded by `_format_argument`, nothing redacted."""
    return {
        "order_id": _format_argument(order_id),
        "account_hash": _format_argument(account_hash),
    }


def _previewed_args(**overrides: str) -> dict[str, str]:
    """Arguments exactly as place_previewed_order in tools/orders.py builds
    them: plain strings, no encoding, full account hash."""
    base = {
        "original_tool": "preview_equity_order",
        "order_summary": "BUY 5 XYZ LIMIT @ 12.34",
        "preview_id": "pv-1",
        "account_hash": _FULL_HASH,
    }
    base.update(overrides)
    return base


def _make_manager(
    monkeypatch: pytest.MonkeyPatch, *, timeout_seconds: float = 600.0
) -> tuple[SignalApprovalManager, list[str]]:
    sent: list[str] = []
    counter = {"ts": 1000}

    async def fake_send(self: SignalApprovalManager, body: str) -> int:
        sent.append(body)
        counter["ts"] += 1
        return counter["ts"]

    async def fake_start(self: SignalApprovalManager) -> None:
        return None

    monkeypatch.setattr(SignalApprovalManager, "_send", fake_send)
    monkeypatch.setattr(SignalApprovalManager, "start", fake_start)

    manager = SignalApprovalManager(
        SignalApprovalSettings(
            api_url="http://127.0.0.1:8080",
            account=_BOT_ACCOUNT,
            approver_numbers=frozenset({_APPROVER}),
            timeout_seconds=timeout_seconds,
        )
    )
    return manager, sent


def _request(**overrides: Any) -> ApprovalRequest:
    base: dict[str, Any] = {
        "id": "appr-1",
        "tool_name": "cancel_order",
        "request_id": "req-1",
        "client_id": None,
        "arguments": _cancel_args(),
    }
    base.update(overrides)
    return ApprovalRequest(**base)


def _reply(
    quoted_ts: int,
    text: str,
    *,
    source: str = _APPROVER,
    quote_author: str = _BOT_ACCOUNT,
) -> dict[str, Any]:
    return {
        "envelope": {
            "sourceNumber": source,
            "dataMessage": {
                "message": text,
                "quote": {"id": quoted_ts, "authorNumber": quote_author},
            },
        }
    }


def test_require_websockets_exposes_exceptions() -> None:
    """websockets>=14 doesn't expose .exceptions as a lazy top-level attribute;
    the helper must import the submodule so the receive loop's except clause
    can reference it on the returned module."""
    module = signal_mod._require_websockets()
    assert module.exceptions.InvalidHandshake is websockets.exceptions.InvalidHandshake


def test_signal_manager_requires_approvers() -> None:
    with pytest.raises(ValueError):
        SignalApprovalManager(
            SignalApprovalSettings(
                api_url="http://127.0.0.1:8080",
                account=_BOT_ACCOUNT,
                approver_numbers=frozenset(),
            )
        )


def test_require_approves_on_ok_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, sent = _make_manager(monkeypatch)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, "ok"))
        decision = await task
        # The decision notice is sent from a background task.
        await asyncio.gather(*manager._notices)
        return decision

    decision = await_result(scenario())

    assert decision is ApprovalDecision.APPROVED
    assert "schwab-mcp" in sent[0]
    assert "approved" in sent[-1]


def test_require_approves_on_sync_message_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linked-device mode: the approver's reply arrives as syncMessage.sentMessage."""
    manager, _ = _make_manager(monkeypatch)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(
            {
                "envelope": {
                    "sourceNumber": _APPROVER,
                    "syncMessage": {
                        "sentMessage": {
                            "message": "ok",
                            "quote": {"id": sent_ts, "authorNumber": _BOT_ACCOUNT},
                        }
                    },
                }
            }
        )
        return await task

    assert await_result(scenario()) is ApprovalDecision.APPROVED


def test_require_denies_on_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, sent = _make_manager(monkeypatch)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, "NO"))
        decision = await task
        await asyncio.gather(*manager._notices)
        return decision

    assert await_result(scenario()) is ApprovalDecision.DENIED
    assert "denied" in sent[-1]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("👍", ApprovalDecision.APPROVED),
        ("✅", ApprovalDecision.APPROVED),
        ("👎", ApprovalDecision.DENIED),
        ("❌", ApprovalDecision.DENIED),
    ],
)
def test_emoji_synonyms_resolve_decisions(
    monkeypatch: pytest.MonkeyPatch, text: str, expected: ApprovalDecision
) -> None:
    manager, _ = _make_manager(monkeypatch)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, text))
        decision = await task
        await asyncio.gather(*manager._notices)
        return decision

    assert await_result(scenario()) is expected


def test_unauthorized_number_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _ = _make_manager(monkeypatch, timeout_seconds=0.05)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, "ok", source="+19998887777"))
        return await task

    assert await_result(scenario()) is ApprovalDecision.EXPIRED


def test_reply_quoting_other_author_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reply quoting someone else's message must not resolve an approval,
    even if its quote.id collides with one of our send timestamps."""
    manager, _ = _make_manager(monkeypatch, timeout_seconds=0.05)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, "ok", quote_author="+19998887777"))
        return await task

    assert await_result(scenario()) is ApprovalDecision.EXPIRED


def test_unrecognized_word_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _ = _make_manager(monkeypatch, timeout_seconds=0.05)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        (sent_ts,) = list(manager._pending)
        await manager._handle_envelope(_reply(sent_ts, "maybe later"))
        return await task

    assert await_result(scenario()) is ApprovalDecision.EXPIRED


def test_reply_without_quote_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _ = _make_manager(monkeypatch, timeout_seconds=0.05)

    async def scenario() -> ApprovalDecision:
        task = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        await manager._handle_envelope(
            {
                "envelope": {
                    "sourceNumber": _APPROVER,
                    "dataMessage": {"message": "ok"},
                }
            }
        )
        return await task

    assert await_result(scenario()) is ApprovalDecision.EXPIRED


def test_duplicate_send_timestamp_denies_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reused send timestamp cannot be correlated safely; both colliding
    approvals are denied."""
    sent: list[str] = []

    async def fake_send(self: SignalApprovalManager, body: str) -> int:
        sent.append(body)
        return 1000

    async def fake_start(self: SignalApprovalManager) -> None:
        return None

    monkeypatch.setattr(SignalApprovalManager, "_send", fake_send)
    monkeypatch.setattr(SignalApprovalManager, "start", fake_start)
    manager = SignalApprovalManager(
        SignalApprovalSettings(
            api_url="http://127.0.0.1:8080",
            account=_BOT_ACCOUNT,
            approver_numbers=frozenset({_APPROVER}),
        )
    )

    async def scenario() -> tuple[ApprovalDecision, ApprovalDecision]:
        first = asyncio.create_task(manager.require(_request()))
        await asyncio.sleep(0)
        second = await manager.require(_request(id="appr-2"))
        return await first, second

    first, second = await_result(scenario())
    # Both prompts share one correlation key, so a reply quoting either is
    # ambiguous; both requests must die.
    assert first is ApprovalDecision.DENIED
    assert second is ApprovalDecision.DENIED
    assert any("duplicate" in body.lower() for body in sent)
    assert manager._pending == {}


def test_require_auto_denies_when_body_overflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, sent = _make_manager(monkeypatch)

    # Use a tool with no friendly renderer so the verbose fallback dumps the
    # arguments verbatim and the body actually overflows.
    decision = await_result(
        manager.require(
            _request(
                tool_name="place_option_combo_order",
                arguments={"legs": "x" * (signal_mod._BODY_LIMIT + 1)},
            )
        )
    )

    assert decision is ApprovalDecision.DENIED
    assert len(sent) == 1
    assert "auto-denied" in sent[0]
    assert manager._pending == {}


def test_timeout_returns_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, sent = _make_manager(monkeypatch, timeout_seconds=0.01)

    decision = await_result(manager.require(_request()))

    assert decision is ApprovalDecision.EXPIRED
    assert "expired" in sent[-1]
    assert manager._pending == {}


def _settings(**overrides: Any) -> SignalApprovalSettings:
    base: dict[str, Any] = {
        "api_url": "http://127.0.0.1:8080",
        "account": _BOT_ACCOUNT,
        "approver_numbers": frozenset({_APPROVER}),
    }
    base.update(overrides)
    return SignalApprovalSettings(**base)


# --------------------------------------------------------------------------- #
# Renderers, driven by the argument shapes production actually produces
# --------------------------------------------------------------------------- #


def test_render_body_cancel_order_with_account_name() -> None:
    manager = SignalApprovalManager(_settings(account_names={"5805": "Rollover IRA"}))
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args()))

    assert "schwab-mcp wants to cancel order 1006299986057 in the Rollover IRA account." in body
    assert _FULL_HASH not in body


def test_render_body_cancel_order_falls_back_to_last4_when_unmapped() -> None:
    manager = SignalApprovalManager(_settings())
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args()))

    assert "in account …5805" in body
    assert _FULL_HASH not in body
    assert "'" not in body.split("\n")[0]  # no repr quote leakage


def test_render_body_place_previewed_order_with_account_name() -> None:
    manager = SignalApprovalManager(_settings(account_names={"5805": "Rollover IRA"}))
    body = manager._render_body(_request(tool_name="place_previewed_order", arguments=_previewed_args()))

    assert (
        "schwab-mcp wants to place a previewed order in the Rollover IRA account: "
        "BUY 5 XYZ LIMIT @ 12.34 (previewed via preview_equity_order)." in body
    )
    assert _FULL_HASH not in body


def test_render_body_place_previewed_order_falls_back_to_last4() -> None:
    manager = SignalApprovalManager(_settings())
    body = manager._render_body(_request(tool_name="place_previewed_order", arguments=_previewed_args()))

    assert "in account …5805" in body
    assert _FULL_HASH not in body


def test_render_body_rejects_crafted_account_hash() -> None:
    """A path-injection account_hash must not be summarized: the last-4
    suffix would present a request targeting a different account and order
    as the legitimate one. The verbose dump shows the raw value instead."""
    manager = SignalApprovalManager(_settings(account_names={"5805": "Rollover IRA"}))
    crafted = "0123456789ABCDEF9999/orders/999000111#5805"
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args(account_hash=crafted)))

    assert "wants to call: cancel_order" in body  # verbose fallback, not the summary
    assert crafted in body  # reviewer sees the raw injected value
    assert "Rollover IRA" not in body


def test_render_body_rejects_non_digit_order_id() -> None:
    """An order_id carrying escaped control characters (e.g. a bidi override)
    must fall back to the verbose dump, which shows repr's escaped form."""
    manager = SignalApprovalManager(_settings())
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args(order_id="123\u202e456")))

    assert "wants to call: cancel_order" in body
    assert "\\u202e" in body  # escaped, as repr produced it
    assert "\u202e" not in body  # the raw override never reaches the message


def test_render_body_rejects_non_alnum_account_hash() -> None:
    """Pre-redacted-style values ("…5805") are not produced by upstream and
    are no longer summarized; they go to the verbose dump."""
    manager = SignalApprovalManager(_settings(account_names={"5805": "Rollover IRA"}))
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args(account_hash="…5805")))

    assert "wants to call: cancel_order" in body
    assert "Rollover IRA" not in body


def test_render_body_survives_truncated_repr() -> None:
    """_format_argument truncates reprs at 256 chars; the broken literal must
    not crash the renderer, and a value that cannot be verified goes to the
    verbose dump rather than into a friendly summary."""
    manager = SignalApprovalManager(_settings())
    long_id = "9" * 300
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args(order_id=long_id)))

    assert "wants to call: cancel_order" in body


def test_render_body_falls_back_to_verbose_for_unknown_tool() -> None:
    manager = SignalApprovalManager(_settings())
    body = manager._render_body(
        _request(
            tool_name="place_option_combo_order",
            arguments={"legs": "['a', 'b']"},
        )
    )

    assert "schwab-mcp wants to call: place_option_combo_order" in body
    assert "legs = " in body
    assert '"ok" to approve' in body


def test_render_body_recovers_from_renderer_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug in a per-tool renderer must never block approvals; the verbose
    fallback always runs."""

    def boom(args: Any, account_names: Any) -> str:
        raise RuntimeError("intentional")

    monkeypatch.setitem(signal_mod._TOOL_RENDERERS, "cancel_order", boom)
    manager = SignalApprovalManager(_settings())
    body = manager._render_body(_request(tool_name="cancel_order", arguments=_cancel_args()))

    assert "schwab-mcp wants to call: cancel_order" in body


def test_parse_account_names_handles_comma_split_and_repeats() -> None:
    parsed = SignalApprovalManager.parse_account_names(
        ["5805=Rollover IRA, 71F7=Roth IRA", "  ", "5805=Rollover IRA v2"]
    )
    assert dict(parsed) == {"5805": "Rollover IRA v2", "71F7": "Roth IRA"}


def test_parse_account_names_skips_malformed_entries() -> None:
    parsed = SignalApprovalManager.parse_account_names(["bogus", "=missing-key", "missing-value=", "5805=OK"])
    assert dict(parsed) == {"5805": "OK"}


def test_authorized_numbers_normalizes() -> None:
    out = SignalApprovalManager.authorized_numbers([" +15555550199 ", "", "+1555"])
    assert out == frozenset({"+15555550199", "+1555"})
    assert SignalApprovalManager.authorized_numbers(None) == frozenset()


def test_agent_name_is_configurable() -> None:
    """The actor named in approval messages comes from settings, not a constant."""
    manager = SignalApprovalManager(_settings(agent_name="Portfolio Bot"))
    body = manager._render_body(_request(tool_name="unknown_tool"))
    assert body.startswith("Portfolio Bot wants to call: unknown_tool")


# --------------------------------------------------------------------------- #
# HTTP transport and websocket receive loop
# --------------------------------------------------------------------------- #


async def _noop_receive_loop(self: SignalApprovalManager) -> None:
    return None


def _mock_transport(captured: dict[str, Any], timestamp: int = 1727) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(201, json={"timestamp": timestamp})

    return httpx.MockTransport(handler)


def _patch_client_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        signal_mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )


def test_send_posts_v2_send_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_client_transport(monkeypatch, _mock_transport(captured))
    monkeypatch.setattr(SignalApprovalManager, "_receive_loop", _noop_receive_loop)
    manager = SignalApprovalManager(_settings(approver_numbers=frozenset({"+15555550199", "+15555550198"})))

    async def scenario() -> int:
        await manager.start()
        ts = await manager._send("hello reviewers")
        await manager.stop()
        return ts

    ts = await_result(scenario())

    assert ts == 1727
    assert captured["url"].endswith("/v2/send")
    assert captured["json"] == {
        "number": _BOT_ACCOUNT,
        "recipients": ["+15555550198", "+15555550199"],
        "message": "hello reviewers",
        "text_mode": "normal",
    }


def test_send_before_start_raises() -> None:
    manager = SignalApprovalManager(_settings())
    with pytest.raises(RuntimeError, match="start"):
        await_result(manager._send("too early"))


def test_manager_is_restartable(monkeypatch: pytest.MonkeyPatch) -> None:
    """start() → stop() → start() must yield a usable client again."""
    captured: dict[str, Any] = {}
    _patch_client_transport(monkeypatch, _mock_transport(captured))
    monkeypatch.setattr(SignalApprovalManager, "_receive_loop", _noop_receive_loop)
    manager = SignalApprovalManager(_settings())

    async def scenario() -> int:
        await manager.start()
        await manager.stop()
        await manager.start()
        ts = await manager._send("after restart")
        await manager.stop()
        return ts

    assert await_result(scenario()) == 1727


class _FakeWebsocket:
    def __init__(self, manager: SignalApprovalManager, frames: list[str]) -> None:
        self._manager = manager
        self._frames = frames

    async def __aenter__(self) -> "_FakeWebsocket":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def __aiter__(self) -> "_FakeWebsocket":
        return self

    async def __anext__(self) -> str:
        # Wait until require() has registered the pending approval, then
        # deliver the reply; afterwards park forever like an idle socket.
        while not self._manager._pending:
            await asyncio.sleep(0)
        if self._frames:
            return self._frames.pop(0)
        await asyncio.Event().wait()
        raise StopAsyncIteration


class _FakeWebsockets:
    exceptions = websockets.exceptions

    def __init__(self, manager: SignalApprovalManager, frames: list[str]) -> None:
        self._manager = manager
        self._frames = frames
        self.connected_urls: list[str] = []

    def connect(self, url: str) -> _FakeWebsocket:
        self.connected_urls.append(url)
        return _FakeWebsocket(self._manager, self._frames)


def test_receive_loop_resolves_approval_from_websocket_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the real start()/require()/_receive_loop wiring:
    a reply frame on the websocket approves the pending request."""
    captured: dict[str, Any] = {}
    _patch_client_transport(monkeypatch, _mock_transport(captured, timestamp=4242))
    manager = SignalApprovalManager(_settings(timeout_seconds=5.0))
    fake_ws = _FakeWebsockets(manager, [json.dumps(_reply(4242, "ok"))])
    monkeypatch.setattr(signal_mod, "_require_websockets", lambda: fake_ws)

    async def scenario() -> ApprovalDecision:
        decision = await manager.require(_request())
        await manager.stop()
        return decision

    decision = await_result(scenario())

    assert decision is ApprovalDecision.APPROVED
    assert fake_ws.connected_urls == [f"ws://127.0.0.1:8080/v1/receive/{_BOT_ACCOUNT}"]


def test_receive_url_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A trailing slash on --signal-api-url must not produce //v1/receive,
    which would 404 on every handshake and read as a daemon-mode problem."""
    captured: dict[str, Any] = {}
    _patch_client_transport(monkeypatch, _mock_transport(captured, timestamp=4242))
    manager = SignalApprovalManager(_settings(api_url="http://127.0.0.1:8080/", timeout_seconds=5.0))
    fake_ws = _FakeWebsockets(manager, [json.dumps(_reply(4242, "ok"))])
    monkeypatch.setattr(signal_mod, "_require_websockets", lambda: fake_ws)

    async def scenario() -> ApprovalDecision:
        decision = await manager.require(_request())
        await manager.stop()
        return decision

    assert await_result(scenario()) is ApprovalDecision.APPROVED
    assert fake_ws.connected_urls == [f"ws://127.0.0.1:8080/v1/receive/{_BOT_ACCOUNT}"]


def test_receive_loop_logs_misconfigured_daemon_mode(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed websocket handshake (daemon not in json-rpc mode) logs a
    specific misconfiguration error instead of a generic reconnect line."""

    class _RefusingWebsockets:
        exceptions = websockets.exceptions

        def connect(self, url: str) -> Any:
            raise websockets.exceptions.InvalidMessage("did not receive a valid HTTP response")

    monkeypatch.setattr(signal_mod, "_require_websockets", lambda: _RefusingWebsockets())
    monkeypatch.setattr(signal_mod, "_MISCONFIG_RETRY_SECONDS", 0.01)
    manager = SignalApprovalManager(_settings())

    async def scenario() -> None:
        task = asyncio.create_task(manager._receive_loop())
        for _ in range(200):
            if any("MODE=json-rpc" in record.getMessage() for record in caplog.records):
                break
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with caplog.at_level("ERROR"):
        await_result(scenario())

    assert any("MODE=json-rpc" in record.getMessage() for record in caplog.records)
