import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, Awaitable, TypeVar, cast

import pytest
from schwab.client import AsyncClient

from mcp.server.fastmcp import Context as MCPContext

from schwab_mcp.approvals import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    DiscordApprovalManager,
    DiscordApprovalSettings,
)
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools import _registration


class RecordingApprovalManager(ApprovalManager):
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision


class DummySession:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.progress: list[dict[str, Any]] = []

    async def send_log_message(self, **payload: Any) -> None:
        self.messages.append(payload)

    async def send_progress_notification(
        self,
        *,
        progress_token: str,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        self.progress.append(
            {
                "progress_token": progress_token,
                "progress": progress,
                "total": total,
                "message": message,
            }
        )


def make_ctx(
    decision: ApprovalDecision,
    *,
    progress_token: str | None = None,
) -> tuple[SchwabContext, RecordingApprovalManager, DummySession, Any]:
    approval_manager = RecordingApprovalManager(decision)
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, object()),
        approval_manager=approval_manager,
    )
    session = DummySession()
    meta = (
        SimpleNamespace(progressToken=progress_token, client_id="client-123")
        if progress_token
        else None
    )
    request_context = SimpleNamespace(
        lifespan_context=lifespan_context,
        request_id="req-123",
        session=session,
        meta=meta,
    )
    ctx = SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )
    return ctx, approval_manager, session, request_context


async def sample_write_tool(ctx: SchwabContext, symbol: str) -> str:
    return symbol.upper()


def wrapped_tool():
    ensured = _registration._ensure_schwab_context(sample_write_tool)
    return _registration._wrap_with_approval(ensured)


T = TypeVar("T")


def await_result(awaitable: Awaitable[T]) -> T:
    async def _runner() -> T:
        return await awaitable

    return asyncio.run(_runner())


def test_write_tool_runs_when_approved() -> None:
    ctx, approval_manager, session, _ = make_ctx(ApprovalDecision.APPROVED)
    tool = wrapped_tool()

    result = await_result(tool(ctx, "spy"))

    assert result == "SPY"
    assert len(approval_manager.requests) == 1
    request = approval_manager.requests[0]
    assert request.tool_name == "sample_write_tool"
    assert request.arguments["symbol"] == "'spy'"
    assert session.messages == []


def test_write_tool_denied_raises_permission_error() -> None:
    ctx, approval_manager, session, _ = make_ctx(ApprovalDecision.DENIED)
    tool = wrapped_tool()

    with pytest.raises(PermissionError):
        await_result(tool(ctx, "spy"))

    assert len(approval_manager.requests) == 1
    assert len(session.messages) == 1
    assert session.messages[0]["level"] == "warning"


def test_write_tool_timeout_raises_timeout_error() -> None:
    ctx, approval_manager, session, _ = make_ctx(ApprovalDecision.EXPIRED)
    tool = wrapped_tool()

    with pytest.raises(TimeoutError):
        await_result(tool(ctx, "spy"))

    assert len(approval_manager.requests) == 1
    assert len(session.messages) == 1
    assert session.messages[0]["level"] == "warning"


def test_write_tool_accepts_base_context() -> None:
    _, approval_manager, session, request_context = make_ctx(ApprovalDecision.APPROVED)
    base_ctx = MCPContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )
    tool = wrapped_tool()

    result = await_result(tool(base_ctx, "spy"))

    assert result == "SPY"
    assert len(approval_manager.requests) == 1
    assert session.messages == []


def test_progress_notifications_emitted_when_supported() -> None:
    ctx, approval_manager, session, _ = make_ctx(
        ApprovalDecision.APPROVED, progress_token="token-1"
    )
    tool = wrapped_tool()

    result = await_result(tool(ctx, "spy"))

    assert result == "SPY"
    assert [entry["progress"] for entry in session.progress] == [0, 1]
    assert session.progress[0]["message"].startswith("Waiting for reviewer approval")
    assert session.progress[1]["message"].startswith("Reviewer approved")


def test_discord_manager_requires_approvers() -> None:
    settings = DiscordApprovalSettings(
        token="token",
        channel_id=123,
        approver_ids=frozenset(),
    )
    with pytest.raises(ValueError):
        DiscordApprovalManager(settings)


# ---------------------------------------------------------------------------
# _wrap_with_approval: missing context-param guard
# ---------------------------------------------------------------------------


def test_wrap_with_approval_raises_when_no_context_param() -> None:
    """Tools without a SchwabContext parameter are rejected at wrap time."""

    async def no_ctx_tool(symbol: str) -> str:
        return symbol

    with pytest.raises(TypeError, match="must accept a SchwabContext parameter"):
        _registration._wrap_with_approval(no_ctx_tool)


# ---------------------------------------------------------------------------
# _wrap_with_approval: context not supplied at call time
# ---------------------------------------------------------------------------


def test_wrap_with_approval_raises_when_context_not_provided() -> None:
    """Calling a wrapped tool without passing the context raises RuntimeError."""

    async def tool_with_ctx(ctx: SchwabContext, value: str) -> str:
        return value

    wrapped = _registration._wrap_with_approval(tool_with_ctx)

    async def runner() -> None:
        # Use bind_partial semantics: omit ctx entirely so it's not in bound.arguments.
        await wrapped(value="hello")  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="missing SchwabContext"):
        asyncio.run(runner())


# ---------------------------------------------------------------------------
# _wrap_with_approval: sync (non-awaitable) result after approval
# ---------------------------------------------------------------------------


def test_wrap_with_approval_handles_sync_result() -> None:
    """A tool that returns synchronously (not awaitable) still works after approval."""

    def sync_tool(ctx: SchwabContext, value: str) -> str:  # type: ignore[return-value]
        return value.upper()

    wrapped = _registration._wrap_with_approval(sync_tool)  # type: ignore[arg-type]
    ctx, _, _, _ = make_ctx(ApprovalDecision.APPROVED)

    result = await_result(wrapped(ctx, "spy"))
    assert result == "SPY"


# ---------------------------------------------------------------------------
# _start_approval_keepalive: task runs iterations then cancels cleanly
# ---------------------------------------------------------------------------


def test_keepalive_task_sends_progress_and_cancels_cleanly(monkeypatch) -> None:
    """The keepalive task emits progress pings and exits on cancellation."""
    ctx, _, session, _ = make_ctx(
        ApprovalDecision.APPROVED, progress_token="tok-keepalive"
    )
    monkeypatch.setattr(_registration, "_APPROVAL_PROGRESS_INTERVAL", 0.001)

    async def runner() -> None:
        task = _registration._start_approval_keepalive(ctx)
        assert task is not None
        # Let the keepalive fire at least once.
        await asyncio.sleep(0.05)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        # At least one keepalive progress notification should have been emitted.
        keepalive_msgs = [
            p for p in session.progress if "elapsed" in (p.get("message") or "")
        ]
        assert len(keepalive_msgs) >= 1

    asyncio.run(runner())


def test_keepalive_not_started_without_progress_token() -> None:
    """No keepalive task is created when the context has no progress token."""
    ctx, _, _, _ = make_ctx(ApprovalDecision.APPROVED)  # no progress_token

    async def runner() -> None:
        task = _registration._start_approval_keepalive(ctx)
        assert task is None

    asyncio.run(runner())


# ---------------------------------------------------------------------------
# _has_progress_token: ValueError from request_context property
# ---------------------------------------------------------------------------


def test_has_progress_token_returns_false_on_value_error() -> None:
    """_has_progress_token returns False when request_context raises ValueError."""

    class _BadContext:
        @property
        def request_context(self) -> Any:
            raise ValueError("not in a request")

    bad_ctx = cast(SchwabContext, _BadContext())
    assert _registration._has_progress_token(bad_ctx) is False
