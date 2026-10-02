"""Signal-based approval backend using a local signal-cli REST daemon."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import httpx

from schwab_mcp.approvals.base import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    format_arguments,
)

logger = logging.getLogger(__name__)


def _require_websockets():
    """Import websockets, failing with install guidance if it is absent."""
    try:
        import websockets
        import websockets.exceptions  # noqa: F401 - not exposed as a lazy top-level attribute
    except ImportError as exc:  # pragma: no cover - exercised only without the dependency
        raise RuntimeError(
            "Signal approvals require the websockets dependency; install it with: pip install 'schwab-mcp[signal]'"
        ) from exc
    return websockets


# Signal's per-message text limit is ~2000 chars; leave headroom for the
# header/footer so the rendered arguments are never partially shown.
_BODY_LIMIT = 1800

# /v2/send is a quick local call; a stalled daemon must not wedge the receive
# loop or an approval's notice, so the client gets a finite timeout.
_HTTP_TIMEOUT_SECONDS = 30.0

# Backoff after a failed websocket handshake. Deliberately long: against a
# daemon in the wrong mode, every GET /v1/receive attempt consumes queued
# messages (and with them any approver replies), so hammering it makes the
# failure worse.
_MISCONFIG_RETRY_SECONDS = 60.0

_APPROVE_WORDS = frozenset({"ok", "yes", "y", "approve", "approved", "✅", "👍"})
_DENY_WORDS = frozenset({"no", "n", "deny", "denied", "❌", "👎"})

_FOOTER = 'Reply "ok" to approve or "no" to deny.'

_EMPTY_NAMES: Mapping[str, str] = MappingProxyType({})


@dataclass(slots=True, frozen=True)
class SignalApprovalSettings:
    """Configuration values required for Signal approvals."""

    api_url: str
    account: str
    approver_numbers: frozenset[str]
    timeout_seconds: float = 600.0
    account_names: Mapping[str, str] = field(default_factory=lambda: _EMPTY_NAMES)
    """Map of last-4-chars of account_hash to a friendly name (e.g. ``5805 ->
    "Rollover IRA"``). Used by the per-tool message renderers to refer to
    accounts by name instead of by redacted-hash suffix. Empty map preserves
    the previous behaviour (always show ``…XXXX``)."""
    agent_name: str = "schwab-mcp"
    """Name used as the actor in approval messages ("<agent_name> wants to
    ..."). Deployments that front an LLM agent can set this to the agent's
    display name so reviewers see who is asking."""


@dataclass(slots=True)
class _PendingApproval:
    request: ApprovalRequest
    future: asyncio.Future[ApprovalDecision]
    sent_timestamp: int


class SignalApprovalManager(ApprovalManager):
    """Approval manager that routes decisions through Signal replies.

    Talks to a local bbernhard/signal-cli-rest-api daemon so no public
    endpoint is exposed. The daemon must run in ``json-rpc`` (or
    ``json-rpc-native``) mode: only those modes serve ``/v1/receive/{number}``
    as a websocket. In ``normal``/``native`` mode the same endpoint performs a
    synchronous receive, which silently consumes approver replies. Correlation
    uses Signal's native reply-to: the daemon returns the sent message's
    timestamp, and an incoming reply carries that timestamp in ``quote.id``.
    """

    def __init__(self, settings: SignalApprovalSettings) -> None:
        if not settings.approver_numbers:
            raise ValueError("SignalApprovalManager requires at least one approver number.")
        _require_websockets()
        self._settings = settings
        # A trailing slash would survive into the receive path ("//v1/receive")
        # and turn every handshake into a 404 that looks like a mode problem.
        self._api_url = settings.api_url.rstrip("/")
        # Created in start() so the manager survives a stop()/start() cycle.
        self._client: httpx.AsyncClient | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._pending: dict[int, _PendingApproval] = {}
        self._notices: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the HTTP client and start the websocket receive loop (idempotent)."""
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._api_url, timeout=_HTTP_TIMEOUT_SECONDS)
        if self._receiver is None:
            loop = asyncio.get_running_loop()
            self._receiver = loop.create_task(self._receive_loop())

    async def stop(self) -> None:
        """Cancel the receive loop and outstanding notices, close the HTTP client."""
        if self._receiver is not None:
            self._receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receiver
            self._receiver = None
        for task in tuple(self._notices):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._notices.clear()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        """Post the approval request over Signal and wait for a reply decision."""
        await self.start()

        body = self._render_body(request)
        if len(body) > _BODY_LIMIT:
            logger.warning(
                "Auto-denying approval %s for tool '%s': body too large to display in full (%d chars)",
                request.id,
                request.tool_name,
                len(body),
            )
            await self._send_best_effort(
                f"❌ schwab-mcp auto-denied '{request.tool_name}' "
                f"(approval {request.id}): arguments too large to display in "
                f"full ({len(body)} chars). Approving a partial view is unsafe."
            )
            return ApprovalDecision.DENIED

        sent_timestamp = await self._send(body)
        future: asyncio.Future[ApprovalDecision] = asyncio.get_running_loop().create_future()
        pending = _PendingApproval(request=request, future=future, sent_timestamp=sent_timestamp)
        async with self._lock:
            colliding = self._pending.pop(sent_timestamp, None)
            if colliding is None:
                self._pending[sent_timestamp] = pending
        if colliding is not None:
            # Two prompts now share one reply-correlation key, so a reply
            # quoting either prompt is ambiguous. Deny both requests.
            if not colliding.future.done():
                colliding.future.set_result(ApprovalDecision.DENIED)
            logger.error(
                "Duplicate Signal send timestamp %d; denying approvals %s and %s for tool '%s'.",
                sent_timestamp,
                colliding.request.id,
                request.id,
                request.tool_name,
            )
            await self._send_best_effort(
                f"❌ schwab-mcp auto-denied '{request.tool_name}' "
                f"(approvals {colliding.request.id} and {request.id}): duplicate "
                f"Signal message timestamp, replies cannot be correlated safely."
            )
            return ApprovalDecision.DENIED

        try:
            decision = await asyncio.wait_for(future, timeout=self._settings.timeout_seconds)
        except asyncio.TimeoutError:
            decision = ApprovalDecision.EXPIRED
            await self._send_best_effort(
                f"⏱️ schwab-mcp approval {request.id} for "
                f"'{request.tool_name}' expired after "
                f"{int(self._settings.timeout_seconds)}s."
            )
        finally:
            async with self._lock:
                self._pending.pop(sent_timestamp, None)

        return decision

    async def _send(self, body: str) -> int:
        if self._client is None:
            raise RuntimeError("SignalApprovalManager.start() must run before sending.")
        response = await self._client.post(
            "/v2/send",
            json={
                "number": self._settings.account,
                "recipients": sorted(self._settings.approver_numbers),
                "message": body,
                # Pin the daemon's text mode: in "styled" mode LLM-supplied
                # text could hide or restyle parts of the approval prompt via
                # ||spoiler||/*italic*/etc. markup.
                "text_mode": "normal",
            },
        )
        response.raise_for_status()
        return int(response.json()["timestamp"])

    async def _send_best_effort(self, body: str) -> None:
        try:
            await self._send(body)
        except httpx.HTTPError:
            logger.exception("Failed to post Signal notice")

    async def _receive_loop(self) -> None:
        websockets = _require_websockets()
        ws_url = self._api_url.replace("http", "ws", 1) + f"/v1/receive/{self._settings.account}"
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    async for frame in ws:
                        await self._handle_envelope(json.loads(frame))
            except asyncio.CancelledError:  # noqa: PERF203 - reconnect-on-error loop needs the handler
                raise
            except websockets.exceptions.InvalidHandshake as exc:
                logger.error(
                    "Signal receive websocket handshake to %s failed: %s. "
                    "bbernhard/signal-cli-rest-api only serves this endpoint as a websocket "
                    "in MODE=json-rpc (or json-rpc-native), and in other modes each connection "
                    "attempt consumes queued messages, so approver replies may be lost. "
                    "Check the daemon mode and --signal-api-url. Retrying in %ds.",
                    ws_url,
                    exc,
                    int(_MISCONFIG_RETRY_SECONDS),
                )
                await asyncio.sleep(_MISCONFIG_RETRY_SECONDS)
            except Exception:
                logger.exception("Signal receive websocket error; reconnecting in 5s")
                await asyncio.sleep(5)

    async def _handle_envelope(self, envelope: dict[str, Any]) -> None:
        env = envelope.get("envelope", envelope)
        source = env.get("sourceNumber") or env.get("source")
        # In linked-device mode the approver's reply is their own outgoing
        # message, delivered to us as syncMessage.sentMessage rather than an
        # incoming dataMessage. Accept either shape.
        sync = (env.get("syncMessage") or {}).get("sentMessage")
        data = env.get("dataMessage") or sync or {}
        quote = data.get("quote") or {}
        quoted_ts = quote.get("id")
        text = (data.get("message") or "").strip().lower()

        if quoted_ts is None or not text:
            return
        if source not in self._settings.approver_numbers:
            logger.debug("Ignoring Signal reply from unauthorized number %s", source)
            return
        quote_author = quote.get("authorNumber") or quote.get("author")
        if quote_author != self._settings.account:
            # The reply quotes someone else's message, so quote.id is not one
            # of our send timestamps and must not resolve a pending approval.
            logger.debug("Ignoring Signal reply quoting %s, not the bot account", quote_author)
            return

        async with self._lock:
            pending = self._pending.get(int(quoted_ts))
        if pending is None or pending.future.done():
            return

        if text in _APPROVE_WORDS:
            decision = ApprovalDecision.APPROVED
        elif text in _DENY_WORDS:
            decision = ApprovalDecision.DENIED
        else:
            return

        pending.future.set_result(decision)
        marker = "✅" if decision is ApprovalDecision.APPROVED else "❌"
        # Send the notice outside the receive loop: an inline await here would
        # block every other reply behind one stalled send.
        self._spawn_notice(
            f"{marker} schwab-mcp approval {pending.request.id} for "
            f"'{pending.request.tool_name}' {decision.value} by {source}."
        )

    def _spawn_notice(self, body: str) -> None:
        task = asyncio.get_running_loop().create_task(self._send_best_effort(body))
        self._notices.add(task)
        task.add_done_callback(self._notices.discard)

    def _render_body(self, request: ApprovalRequest) -> str:
        """Render the Signal message body for an approval request.

        Per-tool renderers produce a one- or two-line natural-language summary
        for the common write tools. Anything we don't have a custom renderer
        for falls back to a slimmed-down YAML-style argument dump.
        """
        renderer = _TOOL_RENDERERS.get(request.tool_name)
        if renderer is not None:
            try:
                args = _decode_arguments(request.arguments)
                summary = renderer(args, self._settings.account_names)
            except ValueError as exc:
                # A value the summary cannot show faithfully (crafted hash,
                # non-digit order id). The verbose dump shows the raw value,
                # so the reviewer sees exactly what would run.
                logger.warning(
                    "Using verbose approval format for tool '%s' (approval %s): %s",
                    request.tool_name,
                    request.id,
                    exc,
                )
            except Exception:
                # Never fail the approval just because the friendly renderer
                # had a bug; fall through to the verbose format so the user
                # still sees the raw arguments and can decide.
                logger.exception(
                    "Friendly renderer failed for tool '%s' (approval %s); falling back to verbose format.",
                    request.tool_name,
                    request.id,
                )
            else:
                return f"{self._settings.agent_name} wants to {summary}\n\n{_FOOTER}"

        rendered_args = format_arguments(request.arguments)
        return f"{self._settings.agent_name} wants to call: {request.tool_name}\n\n{rendered_args}\n\n{_FOOTER}"

    @staticmethod
    def authorized_numbers(values: Sequence[str] | None) -> frozenset[str]:
        """Normalize a sequence of approver phone numbers."""
        if not values:
            return frozenset()
        return frozenset(v.strip() for v in values if v.strip())

    @staticmethod
    def parse_account_names(values: Sequence[str] | None) -> Mapping[str, str]:
        """Parse ``last4=Name`` entries (from CLI flags or comma-split env) into
        an immutable mapping. Repeated keys: last value wins. Whitespace and
        empty entries are ignored. Invalid entries are skipped with a warning.
        """
        if not values:
            return _EMPTY_NAMES
        result: dict[str, str] = {}
        for raw in values:
            if not raw:
                continue
            for chunk in raw.split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "=" not in chunk:
                    logger.warning(
                        "Ignoring malformed account-name entry %r (expected 'last4=Name')",
                        chunk,
                    )
                    continue
                last4, _, name = chunk.partition("=")
                last4 = last4.strip()
                name = name.strip()
                if not last4 or not name:
                    logger.warning("Ignoring empty account-name entry %r", chunk)
                    continue
                result[last4] = name
        return MappingProxyType(result) if result else _EMPTY_NAMES


# --------------------------------------------------------------------------- #
# Per-tool message renderers
# --------------------------------------------------------------------------- #


def _decode_arguments(arguments: Mapping[str, str]) -> dict[str, Any]:
    """Decode the argument values the approval request actually carries.

    Auto-wrapped write tools (``cancel_order``) go through `_format_argument`
    in `tools/_registration.py`, which encodes each value with ``repr()`` and
    truncates at 256 chars; ``ast.literal_eval`` reverses the repr. Tools that
    build their own request (``place_previewed_order`` in `tools/orders.py`)
    pass plain strings, and truncated reprs don't parse; both fall back to the
    raw string so a single odd value never sinks the whole renderer.
    """
    decoded: dict[str, Any] = {}
    for name, raw in arguments.items():
        try:
            decoded[name] = ast.literal_eval(raw)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):  # noqa: PERF203 - per-value fallback is the whole point here
            decoded[name] = raw
    return decoded


def _safe_account_hash(value: Any) -> str | None:
    """Return the account hash if a summary can show it faithfully, None if absent.

    ``account_hash`` is an unvalidated, LLM-supplied string that schwab-py
    formats straight into the request path, and the friendly summary shows
    only its last 4 characters. A crafted value (path separators, URL
    fragments, bidi overrides) could therefore make the prompt describe a
    different target than the request. Summarize only plain ASCII-alphanumeric
    hashes; anything else raises so ``_render_body`` falls back to the verbose
    dump, which shows the raw value.
    """
    if value is None:
        return None
    if isinstance(value, str) and value and value.isascii() and value.isalnum():
        return value
    raise ValueError(f"account_hash cannot be summarized faithfully: {value!r}")


def _account_label(account_value: Any, account_names: Mapping[str, str]) -> str:
    """Resolve the account display label from an ``account_hash`` value.

    Upstream sends the full account hash (nothing redacts it before the
    backend sees it), so derive the last-4 suffix here and never show the
    full hash to reviewers: friendly name if mapped, ``account …XXXX``
    otherwise.
    """
    account_hash = _safe_account_hash(account_value)
    if account_hash is None:
        return "the requested account"
    last4 = account_hash[-4:]
    friendly = account_names.get(last4)
    if friendly:
        return f"the {friendly} account"
    return f"account …{last4}"


def _render_cancel_order(args: Mapping[str, Any], account_names: Mapping[str, str]) -> str:
    order_id = args.get("order_id")
    # Like account_hash, order_id goes into the request path verbatim; only
    # summarize plain ASCII digits so the prompt cannot misrepresent the
    # target. Anything else goes to the verbose dump via the raised error.
    if order_id is not None and not (isinstance(order_id, str) and order_id.isascii() and order_id.isdigit()):
        raise ValueError(f"order_id cannot be summarized faithfully: {order_id!r}")
    account = _account_label(args.get("account_hash"), account_names)
    return f"cancel order {order_id or '?'} in {account}."


def _render_place_previewed_order(args: Mapping[str, Any], account_names: Mapping[str, str]) -> str:
    summary = args.get("order_summary") or "?"
    original_tool = args.get("original_tool") or "a preview tool"
    account = _account_label(args.get("account_hash"), account_names)
    return f"place a previewed order in {account}: {summary} (previewed via {original_tool})."


_TOOL_RENDERERS: Mapping[str, Any] = {
    "place_previewed_order": _render_place_previewed_order,
    "cancel_order": _render_cancel_order,
}


__all__ = ["SignalApprovalManager", "SignalApprovalSettings"]
