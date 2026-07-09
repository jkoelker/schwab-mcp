"""Unit tests for schwab_mcp/approvals/discord.py."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from schwab_mcp.approvals.base import ApprovalDecision, ApprovalRequest
from schwab_mcp.approvals.discord import (
    DiscordApprovalManager,
    DiscordApprovalSettings,
    _PendingApproval,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPROVER_ID = 111
OTHER_USER_ID = 222
CHANNEL_ID = 999


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(
    *,
    approver_ids: frozenset[int] = frozenset({APPROVER_ID}),
    timeout_seconds: float = 5.0,
) -> DiscordApprovalSettings:
    return DiscordApprovalSettings(
        token="fake-token",
        channel_id=CHANNEL_ID,
        approver_ids=approver_ids,
        timeout_seconds=timeout_seconds,
    )


def make_request(
    *,
    id: str = "approval-1",
    tool_name: str = "place_order",
    request_id: str = "req-1",
    client_id: str | None = "client-1",
    arguments: dict[str, str] | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        id=id,
        tool_name=tool_name,
        request_id=request_id,
        client_id=client_id,
        arguments=arguments if arguments is not None else {"symbol": "AAPL", "qty": "10"},
    )


def make_manager(
    settings: DiscordApprovalSettings | None = None,
) -> DiscordApprovalManager:
    """Return a manager whose _ApprovalClient is fully mocked out."""
    if settings is None:
        settings = make_settings()
    with patch("schwab_mcp.approvals.discord._ApprovalClient"):
        mgr = DiscordApprovalManager(settings)

    # Replace with a clean MagicMock so we can configure it per-test
    client: Any = MagicMock()
    client.close = AsyncMock()
    client.start = AsyncMock()
    client.get_channel = MagicMock(return_value=None)
    client.fetch_channel = AsyncMock()
    mgr._client = client
    return mgr


def make_fake_channel() -> Any:
    channel: Any = MagicMock()
    channel.id = CHANNEL_ID
    channel.send = AsyncMock()
    return channel


def make_fake_message(channel: Any) -> Any:
    msg: Any = MagicMock()
    msg.id = 42
    msg.channel = channel
    msg.add_reaction = AsyncMock()
    msg.edit = AsyncMock()
    return msg


def make_fake_reaction(msg: Any, emoji: str) -> Any:
    reaction: Any = MagicMock()
    reaction.emoji = emoji
    reaction.message = msg
    reaction.remove = AsyncMock()
    return reaction


def make_fake_user(user_id: int, *, bot: bool = False) -> Any:
    user: Any = MagicMock()
    user.id = user_id
    user.bot = bot
    return user


def inject_pending(mgr: DiscordApprovalManager, msg: Any) -> asyncio.Future[ApprovalDecision]:
    """Register a _PendingApproval and return the future for direct resolution."""
    future: asyncio.Future[ApprovalDecision] = asyncio.get_running_loop().create_future()
    mgr._pending[msg.id] = _PendingApproval(request=make_request(), future=future, message=msg)
    return future


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_requires_at_least_one_approver_id() -> None:
    with (
        pytest.raises(ValueError, match="at least one approver ID"),
        patch("schwab_mcp.approvals.discord._ApprovalClient"),
    ):
        DiscordApprovalManager(make_settings(approver_ids=frozenset()))


# ---------------------------------------------------------------------------
# start() / stop() lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_start_launches_runner_task_and_waits_for_ready() -> None:
    mgr = make_manager()
    # Pre-set the ready event so start() does not block
    mgr._ready.set()

    async def fake_run_client() -> None:
        await asyncio.sleep(0)

    mgr._run_client = fake_run_client  # type: ignore[method-assign]

    await mgr.start()
    assert mgr._runner is not None

    # Clean up
    runner = mgr._runner
    runner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await runner


@pytest.mark.anyio
async def test_start_is_idempotent() -> None:
    mgr = make_manager()
    mgr._ready.set()

    async def fake_run_client() -> None:
        await asyncio.sleep(100)

    mgr._run_client = fake_run_client  # type: ignore[method-assign]

    await mgr.start()
    first_runner = mgr._runner

    await mgr.start()  # second call — must be a no-op
    assert mgr._runner is first_runner

    runner = mgr._runner
    if runner is not None:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner


@pytest.mark.anyio
async def test_stop_clears_state() -> None:
    mgr = make_manager()
    mgr._ready.set()
    mgr._channel = make_fake_channel()

    async def noop() -> None:
        pass

    loop = asyncio.get_running_loop()
    mgr._runner = loop.create_task(noop())
    await asyncio.sleep(0)  # let the task finish naturally

    await mgr.stop()

    assert mgr._runner is None
    assert mgr._channel is None
    assert not mgr._ready.is_set()
    mgr._client.close.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_stop_when_not_started_is_safe() -> None:
    mgr = make_manager()
    await mgr.stop()
    mgr._client.close.assert_not_awaited()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _handle_ready()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_ready_sets_ready_event() -> None:
    mgr = make_manager()
    assert not mgr._ready.is_set()
    await mgr._handle_ready()
    assert mgr._ready.is_set()


# ---------------------------------------------------------------------------
# _ensure_channel()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ensure_channel_returns_cached_channel() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    mgr._channel = channel

    result = await mgr._ensure_channel()

    assert result is channel
    mgr._client.get_channel.assert_not_called()  # type: ignore[attr-defined]
    mgr._client.fetch_channel.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_ensure_channel_uses_get_channel_when_available() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel: Any = MagicMock(spec=discord.TextChannel)
    mgr._client.get_channel.return_value = channel  # type: ignore[attr-defined]

    result = await mgr._ensure_channel()

    assert result is channel
    mgr._client.fetch_channel.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_ensure_channel_fetches_when_get_channel_returns_none() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel: Any = MagicMock(spec=discord.TextChannel)
    mgr._client.get_channel.return_value = None  # type: ignore[attr-defined]
    mgr._client.fetch_channel = AsyncMock(return_value=channel)  # type: ignore[attr-defined]

    result = await mgr._ensure_channel()

    assert result is channel
    mgr._client.fetch_channel.assert_awaited_once_with(CHANNEL_ID)  # type: ignore[attr-defined]
    assert mgr._channel is channel


@pytest.mark.anyio
async def test_ensure_channel_raises_if_not_messageable() -> None:
    mgr = make_manager()
    mgr._ready.set()
    bad_channel: Any = MagicMock(spec=discord.VoiceChannel)
    mgr._client.get_channel.return_value = None  # type: ignore[attr-defined]
    mgr._client.fetch_channel = AsyncMock(return_value=bad_channel)  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="not messageable"):
        await mgr._ensure_channel()


# ---------------------------------------------------------------------------
# require(): success path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_require_approved_via_reaction() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def drive_approval() -> None:
        await asyncio.sleep(0)
        pending = mgr._pending.get(msg.id)
        if pending and not pending.future.done():
            pending.future.set_result(ApprovalDecision.APPROVED)

    asyncio.get_running_loop().create_task(drive_approval())
    decision = await mgr.require(make_request())

    assert decision == ApprovalDecision.APPROVED
    channel.send.assert_awaited_once()
    msg.add_reaction.assert_any_await("✅")
    msg.add_reaction.assert_any_await("❌")


@pytest.mark.anyio
async def test_require_denied_via_reaction() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def drive_denial() -> None:
        await asyncio.sleep(0)
        pending = mgr._pending.get(msg.id)
        if pending and not pending.future.done():
            pending.future.set_result(ApprovalDecision.DENIED)

    asyncio.get_running_loop().create_task(drive_denial())
    decision = await mgr.require(make_request())

    assert decision == ApprovalDecision.DENIED


@pytest.mark.anyio
async def test_require_cleans_up_pending_after_decision() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def resolve() -> None:
        await asyncio.sleep(0)
        pending = mgr._pending.get(msg.id)
        if pending:
            pending.future.set_result(ApprovalDecision.APPROVED)

    asyncio.get_running_loop().create_task(resolve())
    await mgr.require(make_request())

    assert msg.id not in mgr._pending


@pytest.mark.anyio
async def test_require_sends_pending_embed_with_tool_name() -> None:
    """require() must pass an embed whose description mentions the tool name."""
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def resolve() -> None:
        await asyncio.sleep(0)
        pending = mgr._pending.get(msg.id)
        if pending:
            pending.future.set_result(ApprovalDecision.APPROVED)

    asyncio.get_running_loop().create_task(resolve())
    await mgr.require(make_request(tool_name="my_special_tool"))

    call_kwargs = channel.send.call_args
    embed: discord.Embed = call_kwargs.kwargs["embed"]
    assert "my_special_tool" in (embed.description or "")


# ---------------------------------------------------------------------------
# require(): timeout path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_require_times_out_returns_expired() -> None:
    mgr = make_manager(make_settings(timeout_seconds=0.01))
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    decision = await mgr.require(make_request())

    assert decision == ApprovalDecision.EXPIRED
    msg.edit.assert_awaited_once()


@pytest.mark.anyio
async def test_require_times_out_cleans_up_pending() -> None:
    mgr = make_manager(make_settings(timeout_seconds=0.01))
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    await mgr.require(make_request())

    assert msg.id not in mgr._pending


# ---------------------------------------------------------------------------
# require(): HTTPException on add_reaction
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_require_denied_when_add_reaction_raises_http_exception() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    msg.add_reaction = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=403), "Forbidden"))
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    decision = await mgr.require(make_request())

    assert decision == ApprovalDecision.DENIED
    msg.edit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_reaction_add(): authorization and routing logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_reaction_add_approved_by_authorized_user() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "✅")
    user = make_fake_user(APPROVER_ID)

    await mgr._handle_reaction_add(reaction, user)

    assert future.done()
    assert future.result() == ApprovalDecision.APPROVED
    msg.edit.assert_awaited_once()


@pytest.mark.anyio
async def test_handle_reaction_add_denied_by_authorized_user() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "❌")
    user = make_fake_user(APPROVER_ID)

    await mgr._handle_reaction_add(reaction, user)

    assert future.result() == ApprovalDecision.DENIED


@pytest.mark.anyio
async def test_handle_reaction_add_ignores_bot_reactions() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "✅")
    bot_user = make_fake_user(APPROVER_ID, bot=True)

    await mgr._handle_reaction_add(reaction, bot_user)

    assert not future.done()


@pytest.mark.anyio
async def test_handle_reaction_add_ignores_wrong_channel() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    channel.id = 12345  # different from CHANNEL_ID
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "✅")
    user = make_fake_user(APPROVER_ID)

    await mgr._handle_reaction_add(reaction, user)

    assert not future.done()


@pytest.mark.anyio
async def test_handle_reaction_add_ignores_unknown_message() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    # Nothing registered in _pending — should complete silently

    reaction = make_fake_reaction(msg, "✅")
    user = make_fake_user(APPROVER_ID)

    await mgr._handle_reaction_add(reaction, user)  # must not raise


@pytest.mark.anyio
async def test_handle_reaction_add_ignores_unrecognized_emoji() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "🤔")
    user = make_fake_user(APPROVER_ID)

    await mgr._handle_reaction_add(reaction, user)

    assert not future.done()


@pytest.mark.anyio
async def test_handle_reaction_add_removes_unauthorized_user_reaction() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "✅")
    unauthorized_user = make_fake_user(OTHER_USER_ID)

    await mgr._handle_reaction_add(reaction, unauthorized_user)

    assert not future.done()
    reaction.remove.assert_awaited_once_with(unauthorized_user)


@pytest.mark.anyio
async def test_handle_reaction_add_unauthorized_remove_survives_http_exception() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    reaction = make_fake_reaction(msg, "✅")
    reaction.remove = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=403), "Forbidden"))
    unauthorized_user = make_fake_user(OTHER_USER_ID)

    await mgr._handle_reaction_add(reaction, unauthorized_user)  # must not raise

    assert not future.done()


@pytest.mark.anyio
async def test_handle_reaction_add_skips_already_resolved_future() -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)
    future.set_result(ApprovalDecision.APPROVED)  # already resolved

    reaction = make_fake_reaction(msg, "✅")
    user = make_fake_user(APPROVER_ID)

    # Must not raise InvalidStateError on future.set_result
    await mgr._handle_reaction_add(reaction, user)
    # _finalize_message / msg.edit must not be called a second time
    msg.edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# authorized_user_ids() static helper
# ---------------------------------------------------------------------------


def test_authorized_user_ids_normalizes_sequence() -> None:
    result = DiscordApprovalManager.authorized_user_ids([1, 2, 3])
    assert result == frozenset({1, 2, 3})


def test_authorized_user_ids_returns_empty_frozenset_for_none() -> None:
    assert DiscordApprovalManager.authorized_user_ids(None) == frozenset()


def test_authorized_user_ids_returns_empty_frozenset_for_empty_list() -> None:
    assert DiscordApprovalManager.authorized_user_ids([]) == frozenset()
