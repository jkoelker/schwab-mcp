from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from conftest import make_ctx, run
from schwab.client import AsyncClient as SchwabAsyncClient

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.tools import orders


class ReplacementClient:
    class Instrument:
        Projection = {"SYMBOL_SEARCH": "SYMBOL_SEARCH"}

    def __init__(self) -> None:
        self.preview_payload: dict[str, Any] | None = None
        self.replacement_payload: dict[str, Any] | None = None
        self.replacement_calls = 0
        self.place_calls = 0

    async def preview_order(self, **kwargs: Any) -> dict[str, Any]:
        self.preview_payload = kwargs
        return {"previewed": True}

    async def get_instruments(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        return {"instruments": [{"symbol": symbol, "assetType": "EQUITY"}]}

    async def replace_order(self, **kwargs: Any) -> dict[str, Any]:
        self.replacement_calls += 1
        self.replacement_payload = kwargs
        return {"orderId": "replaced-10"}

    async def place_order(self, **kwargs: Any) -> dict[str, Any]:
        self.place_calls += 1
        return {"orderId": "placed-10"}

    async def get_order(self, **kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("status unavailable")


class RecordingApproval(ApprovalManager):
    def __init__(self, decision: ApprovalDecision = ApprovalDecision.APPROVED) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []
        self.error: Exception | None = None
        self.entered: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.decision


def replacement_description() -> orders._OrderDescInput:
    return cast(
        orders._OrderDescInput,
        {
            "symbol": "SPY 251219C500",
            "quantity": 1,
            "instruction": "BUY_TO_OPEN",
            "order_type": "MARKET",
            "asset_type": "OPTION",
        },
    )


async def call_fake_client(func: Any, *args: Any, **kwargs: Any) -> Any:
    return await func(*args, **kwargs)


def mock_schwab_client(transport: httpx.AsyncBaseTransport) -> tuple[SchwabAsyncClient, httpx.AsyncClient]:
    session = httpx.AsyncClient(transport=transport)
    return SchwabAsyncClient("test-api-key", session), session


def test_replacement_uses_immutable_preview_and_exact_bound_target(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    replacement: dict[str, Any] = {
        "symbol": "SPY 251219C500",
        "quantity": 2,
        "instruction": "BUY_TO_OPEN",
        "order_type": "LIMIT",
        "asset_type": "OPTION",
        "price": 1.239,
        "session": "AM",
        "duration": "DAY",
    }

    result = run(
        orders.preview_replacement_order(
            ctx, "account-opaque", " padded-order-9 ", cast(orders._OrderDescInput, replacement)
        )
    )
    replacement["quantity"] = 999

    placed = run(orders.replace_previewed_order(ctx, "account-opaque", result["preview_id"]))

    assert placed == {
        "orderId": "replaced-10",
        "accountHash": "account-opaque",
        "note": "Order replaced; status fetch failed",
    }
    preview_payload = client.preview_payload
    replacement_payload = client.replacement_payload
    assert preview_payload is not None
    assert replacement_payload is not None
    assert preview_payload["account_hash"] == "account-opaque"
    assert replacement_payload["account_hash"] == "account-opaque"
    assert replacement_payload["order_id"] == "padded-order-9"
    assert replacement_payload["order_spec"] == preview_payload["order_spec"]
    assert replacement_payload["order_spec"]["orderLegCollection"][0]["quantity"] == 2
    assert approval_manager.requests[0].arguments["target_order_id"] == "padded-order-9"
    assert approval_manager.requests[0].arguments["order_summary"] == (
        "BUY_TO_OPEN 2 SPY 251219C500 LIMIT @ $1.23 OPTION session=AM duration=DAY"
    )


@pytest.mark.parametrize(
    ("replacement", "expected_summary"),
    [
        (
            {
                "symbol": "SPY 251219C500",
                "quantity": 1,
                "instruction": "BUY_TO_OPEN",
                "order_type": "LIMIT",
                "asset_type": "OPTION",
                "price": 0.12349,
                "session": "PM",
                "duration": "GTC",
            },
            "BUY_TO_OPEN 1 SPY 251219C500 LIMIT @ $0.1234 OPTION session=PM duration=GOOD_TILL_CANCEL",
        ),
        (
            {
                "symbol": "AAPL",
                "quantity": 3,
                "instruction": "SELL",
                "order_type": "STOP",
                "stop_price": 10.129,
            },
            "SELL 3 AAPL STOP stop $10.12 session=NORMAL duration=DAY",
        ),
        (
            {
                "symbol": "AAPL",
                "quantity": 3,
                "instruction": "SELL",
                "order_type": "TRAILING_STOP",
                "trail_offset": 1.23456789,
                "trail_type": "PERCENT",
            },
            "SELL 3 AAPL TRAILING_STOP offset=1.23456789 PERCENT session=NORMAL duration=DAY",
        ),
    ],
)
def test_approval_summary_matches_canonical_price_and_settings(
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict[str, Any],
    expected_summary: str,
) -> None:
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    preview = run(orders.preview_replacement_order(ctx, "account", "target", cast(orders._OrderDescInput, replacement)))

    run(orders.replace_previewed_order(ctx, "account", preview["preview_id"]))

    assert approval_manager.requests[0].arguments["order_summary"] == expected_summary


def test_wrong_account_does_not_consume_replacement_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager

    monkeypatch.setattr(orders, "call", call_fake_client)
    result = run(
        orders.preview_replacement_order(
            ctx,
            "account-opaque",
            "target-1",
            cast(
                orders._OrderDescInput,
                {
                    "symbol": "SPY 251219C500",
                    "quantity": 1,
                    "instruction": "BUY_TO_OPEN",
                    "order_type": "MARKET",
                    "asset_type": "OPTION",
                },
            ),
        )
    )

    with pytest.raises(ValueError, match="Account hash mismatch"):
        run(orders.replace_previewed_order(ctx, "other-account", result["preview_id"]))
    assert approval_manager.requests == []
    assert client.replacement_payload is None
    assert client.replacement_calls == 0
    run(orders.replace_previewed_order(ctx, "account-opaque", result["preview_id"]))
    assert len(approval_manager.requests) == 1


def test_wrong_operation_preserves_replacement_preview_for_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    result = run(orders.preview_replacement_order(ctx, "account", "target", replacement_description()))

    with pytest.raises(ValueError, match="operation mismatch"):
        run(orders.place_previewed_order(ctx, "account", result["preview_id"]))
    assert approval_manager.requests == []
    assert client.replacement_payload is None

    run(orders.replace_previewed_order(ctx, "account", result["preview_id"]))
    assert len(approval_manager.requests) == 1
    assert client.replacement_payload is not None
    assert client.replacement_payload["order_id"] == "target"
    assert client.replacement_calls == 1


def test_wrong_operation_preserves_placement_preview_for_place(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    result = run(
        orders.preview_option_order(
            ctx,
            "account",
            "SPY 251219C500",
            1,
            "BUY_TO_OPEN",
            "MARKET",
        )
    )

    with pytest.raises(ValueError, match="operation mismatch"):
        run(orders.replace_previewed_order(ctx, "account", result["preview_id"]))
    assert approval_manager.requests == []
    assert client.place_calls == 0
    run(orders.place_previewed_order(ctx, "account", result["preview_id"]))
    assert len(approval_manager.requests) == 1
    assert client.place_calls == 1
    assert client.replacement_calls == 0


@pytest.mark.parametrize("failure", ["unknown", "expired", "reused"])
def test_unavailable_preview_has_no_approval_or_write(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    import schwab_mcp.previews as previews

    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    now = [100.0]
    monkeypatch.setattr(previews, "time", SimpleNamespace(monotonic=lambda: now[0]))
    result = run(orders.preview_replacement_order(ctx, "account", "target", replacement_description()))
    preview_id = result["preview_id"]

    if failure == "unknown":
        preview_id = "not-a-preview"
    elif failure == "expired":
        now[0] += 601
    else:
        run(orders.replace_previewed_order(ctx, "account", preview_id))
        client.replacement_payload = None

    with pytest.raises(ValueError, match="not found or expired"):
        run(orders.replace_previewed_order(ctx, "account", preview_id))
    assert len(approval_manager.requests) == (1 if failure == "reused" else 0)
    assert client.replacement_payload is None
    assert client.replacement_calls == (1 if failure == "reused" else 0)


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [("denied", PermissionError), ("decision-expired", TimeoutError), ("raised-timeout", TimeoutError)],
)
def test_failed_approval_consumes_preview_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_error: type[Exception],
) -> None:
    decision = ApprovalDecision.DENIED if outcome == "denied" else ApprovalDecision.EXPIRED
    client = ReplacementClient()
    ctx = make_ctx(client)
    approval_manager = RecordingApproval(decision)
    if outcome == "raised-timeout":
        approval_manager.error = TimeoutError("approval transport timed out")
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    result = run(orders.preview_replacement_order(ctx, "account", "target", replacement_description()))

    with pytest.raises(expected_error):
        run(orders.replace_previewed_order(ctx, "account", result["preview_id"]))
    assert len(approval_manager.requests) == 1
    assert client.replacement_payload is None
    assert client.replacement_calls == 0
    with pytest.raises(ValueError, match="not found or expired"):
        run(orders.replace_previewed_order(ctx, "account", result["preview_id"]))
    assert len(approval_manager.requests) == 1


def test_concurrent_reuse_has_one_approval_and_admission_survives_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import schwab_mcp.previews as previews

    client = ReplacementClient()
    ctx = make_ctx(client)
    now = [200.0]
    monkeypatch.setattr(previews, "time", SimpleNamespace(monotonic=lambda: now[0]))
    approval_manager = RecordingApproval()
    ctx.schwab.approval_manager = approval_manager
    monkeypatch.setattr(orders, "call", call_fake_client)
    result = run(orders.preview_replacement_order(ctx, "account", "target", replacement_description()))

    async def scenario() -> None:
        approval_manager.entered = asyncio.Event()
        approval_manager.release = asyncio.Event()
        pending = asyncio.create_task(orders.replace_previewed_order(ctx, "account", result["preview_id"]))
        try:
            await asyncio.wait_for(approval_manager.entered.wait(), timeout=1)
            with pytest.raises(ValueError, match="not found or expired"):
                await asyncio.wait_for(orders.replace_previewed_order(ctx, "account", result["preview_id"]), timeout=1)
            assert client.replacement_payload is None
            now[0] += 601
            approval_manager.release.set()
            await asyncio.wait_for(pending, timeout=1)
        finally:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending

    asyncio.run(scenario())
    assert len(approval_manager.requests) == 1
    assert client.replacement_payload is not None
    assert client.replacement_payload["order_id"] == "target"
    assert client.replacement_calls == 1


@pytest.mark.parametrize("unsafe_id", [".", "..", "a/b", "a?b", "a#b", "a\\b", "a%2Fb", "a\nb"])
def test_replacement_rejects_url_structural_target_ids(unsafe_id: str) -> None:
    client = ReplacementClient()
    with pytest.raises(ValueError, match="order_id must contain only ASCII"):
        run(
            orders.preview_replacement_order(
                make_ctx(client),
                "account-opaque",
                unsafe_id,
                cast(
                    orders._OrderDescInput,
                    {
                        "symbol": "SPY 251219C500",
                        "quantity": 1,
                        "instruction": "BUY_TO_OPEN",
                        "order_type": "MARKET",
                        "asset_type": "OPTION",
                    },
                ),
            )
        )
    assert client.preview_payload is None
    assert client.replacement_payload is None
    assert client.replacement_calls == 0


@pytest.mark.parametrize("preview_kind", ["regular", "replacement"])
def test_malicious_preview_account_hash_makes_no_http_requests(preview_kind: str) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={}, request=request)

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        client, session = mock_schwab_client(transport)
        ctx = make_ctx(client)
        try:
            with pytest.raises(ValueError, match="account_hash"):
                if preview_kind == "regular":
                    await orders.preview_equity_order(ctx, "HASH/orders#", "AAPL", 1, "BUY", "MARKET")
                else:
                    await orders.preview_replacement_order(
                        ctx,
                        "HASH/orders#",
                        "order-1",
                        cast(
                            orders._OrderDescInput,
                            {
                                "symbol": "AAPL",
                                "quantity": 1,
                                "instruction": "BUY",
                                "order_type": "MARKET",
                            },
                        ),
                    )
        finally:
            await session.aclose()

    run(scenario())
    assert requests == []


@pytest.mark.parametrize(
    ("account_hash", "order_id"),
    [("HASH/orders#", "order-1"), ("HASH_123", "order/1")],
)
def test_malicious_cancel_identifiers_fail_before_approval_or_http(account_hash: str, order_id: str) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    async def scenario() -> None:
        client, session = mock_schwab_client(httpx.MockTransport(handler))
        ctx = make_ctx(client)
        approval_manager = RecordingApproval()
        ctx.schwab.approval_manager = approval_manager
        try:
            with pytest.raises(ValueError):
                await orders.cancel_order(ctx, account_hash, order_id)
        finally:
            await session.aclose()
        assert approval_manager.requests == []

    run(scenario())
    assert requests == []


def test_valid_identifiers_are_preserved_in_schwab_http_requests() -> None:
    requests: list[httpx.Request] = []
    approval_manager = RecordingApproval()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        if request.url.path.endswith("/instruments"):
            return httpx.Response(200, json={"instruments": [{"assetType": "EQUITY"}]}, request=request)
        if request.method == "POST":
            return httpx.Response(200, json={"previewed": True}, request=request)
        return httpx.Response(200, json={"orderId": "order_123", "status": "WORKING"}, request=request)

    async def scenario() -> None:
        client, session = mock_schwab_client(httpx.MockTransport(handler))
        ctx = make_ctx(client)
        ctx.schwab.approval_manager = approval_manager
        try:
            await orders.preview_equity_order(ctx, "HASH_123-abc", "AAPL", 1, "BUY", "MARKET")
            await orders.cancel_order(ctx, "HASH_123-abc", "order_123")
        finally:
            await session.aclose()

    run(scenario())
    urls = [str(request.url) for request in requests]
    assert any("HASH_123-abc" in url for url in urls)
    assert any("order_123" in url for url in urls)
    assert any(request.method == "POST" for request in requests)
    assert any(request.method == "DELETE" for request in requests)
    assert len(approval_manager.requests) == 1
    assert approval_manager.requests[0].arguments == {
        "account_hash": "'HASH_123-abc'",
        "order_id": "'order_123'",
    }
