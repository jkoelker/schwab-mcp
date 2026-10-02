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


async def wait_until_pending(mgr: DiscordApprovalManager, msg: Any) -> None:
    async def poll() -> None:
        while msg.id not in mgr._pending:
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=1.0)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_requires_at_least_one_approver_id() -> None:
    with (
        pytest.raises(ValueError, match="at least one approver ID"),
        patch("schwab_mcp.approvals.discord._ApprovalClient"),
    ):
        DiscordApprovalManager(make_settings(approver_ids=frozenset()))


@pytest.mark.anyio
async def test_pending_message_preserves_late_order_arguments() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    message = make_fake_message(channel)
    pending_registered = asyncio.Event()

    class PendingApprovals(dict[int, _PendingApproval]):
        def __setitem__(self, key: int, value: _PendingApproval) -> None:
            super().__setitem__(key, value)
            pending_registered.set()

    mgr._pending = PendingApprovals()

    message.add_reaction = AsyncMock()
    channel.send.return_value = message
    mgr._channel = channel
    mgr.start = AsyncMock()  # type: ignore[method-assign]
    request = make_request(
        arguments={
            "summary": "x" * 960,
            "account": "1234",
            "target": "replace order 5678",
        }
    )

    approval = asyncio.create_task(mgr.require(request))
    try:
        await asyncio.wait_for(pending_registered.wait(), timeout=1)
        reaction = make_fake_reaction(message, "✅")
        user = make_fake_user(APPROVER_ID)
        await mgr._handle_reaction_add(reaction, user)
        assert await asyncio.wait_for(approval, timeout=1) is ApprovalDecision.APPROVED
    finally:
        if not approval.done():
            approval.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await approval

    embed = channel.send.await_args.kwargs["embed"]
    argument_field = next(field.value for field in embed.fields if field.name == "Arguments")
    assert "account" in argument_field and "1234" in argument_field
    assert "target" in argument_field and "replace order 5678" in argument_field


@pytest.mark.anyio
async def test_oversized_arguments_are_denied_with_notice_not_approval() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    mgr._channel = channel
    mgr.start = AsyncMock()  # type: ignore[method-assign]
    request = make_request(arguments={"summary": "x" * 1025, "account": "1234"})

    assert await asyncio.wait_for(mgr.require(request), timeout=1) is ApprovalDecision.DENIED

    channel.send.assert_awaited_once()
    assert channel.send.await_args.kwargs == {
        "content": "❌ schwab-mcp auto-denied 'place_order' (approval approval-1): "
        "arguments exceed Discord's 1024-character display limit. "
        "Approving a partial view is unsafe."
    }


@pytest.mark.anyio
async def test_oversized_arguments_remain_denied_if_notice_send_fails() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Server error"))
    mgr._channel = channel
    mgr.start = AsyncMock()  # type: ignore[method-assign]

    decision = await asyncio.wait_for(mgr.require(make_request(arguments={"summary": "x" * 1025})), timeout=1)

    assert decision is ApprovalDecision.DENIED
    channel.send.assert_awaited_once()


@pytest.mark.anyio
async def test_oversized_arguments_remain_denied_if_channel_lookup_fails() -> None:
    mgr = make_manager()
    mgr._ready.set()
    mgr.start = AsyncMock()  # type: ignore[method-assign]
    mgr._client.fetch_channel = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Server error"))

    decision = await asyncio.wait_for(mgr.require(make_request(arguments={"summary": "x" * 1025})), timeout=1)

    assert decision is ApprovalDecision.DENIED
    mgr._client.fetch_channel.assert_awaited_once_with(CHANNEL_ID)
    assert mgr._pending == {}


@pytest.mark.anyio
async def test_pending_message_sanitizes_markdown_in_arguments() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    message = make_fake_message(channel)
    pending_registered = asyncio.Event()

    class PendingApprovals(dict[int, _PendingApproval]):
        def __setitem__(self, key: int, value: _PendingApproval) -> None:
            super().__setitem__(key, value)
            pending_registered.set()

    mgr._pending = PendingApprovals()

    message.add_reaction = AsyncMock()
    channel.send.return_value = message
    mgr._channel = channel
    mgr.start = AsyncMock()  # type: ignore[method-assign]
    request = make_request(
        arguments={
            "account`**": "123`4 **bold** [link](https://example.com) <@123456789012345678>",
        }
    )

    approval = asyncio.create_task(mgr.require(request))
    try:
        await asyncio.wait_for(pending_registered.wait(), timeout=1)
        reaction = make_fake_reaction(message, "✅")
        user = make_fake_user(APPROVER_ID)
        await mgr._handle_reaction_add(reaction, user)
        assert await asyncio.wait_for(approval, timeout=1) is ApprovalDecision.APPROVED
    finally:
        if not approval.done():
            approval.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await approval

    embed = channel.send.await_args.kwargs["embed"]
    argument_field = next(field.value for field in embed.fields if field.name == "Arguments")
    assert "accountˋ**" in argument_field
    assert "123ˋ4 **bold** [link](https://example.com)" in argument_field
    assert "<@\u200b123456789012345678>" in argument_field
    assert argument_field.startswith("```\n") and argument_field.endswith("\n```")


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


@pytest.mark.parametrize(
    ("emoji", "expected"),
    [("✅", ApprovalDecision.APPROVED), ("❌", ApprovalDecision.DENIED)],
)
@pytest.mark.anyio
async def test_require_records_authorized_reaction(emoji: str, expected: ApprovalDecision) -> None:
    mgr = make_manager()
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def submit_reaction() -> None:
        await wait_until_pending(mgr, msg)
        await mgr._handle_reaction_add(make_fake_reaction(msg, emoji), make_fake_user(APPROVER_ID))

    reaction_task = asyncio.create_task(submit_reaction())
    decision = await mgr.require(make_request())
    await reaction_task

    assert decision == expected
    assert msg.id not in mgr._pending
    embed: discord.Embed = msg.edit.call_args.kwargs["embed"]
    assert expected.value in (embed.title or "")
    fields = {field.name: field.value for field in embed.fields}
    assert str(APPROVER_ID) in (fields["Actor"] or "")
    assert emoji in (fields["Notes"] or "")
    assert {call.args[0] for call in msg.add_reaction.await_args_list} == {"✅", "❌"}


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


@pytest.mark.parametrize(
    ("user_id", "bot", "emoji", "channel_id"),
    [
        pytest.param(OTHER_USER_ID, False, "✅", CHANNEL_ID, id="unauthorized-user"),
        pytest.param(APPROVER_ID, True, "✅", CHANNEL_ID, id="bot"),
        pytest.param(APPROVER_ID, False, "✅", CHANNEL_ID + 1, id="wrong-channel"),
        pytest.param(APPROVER_ID, False, "🤔", CHANNEL_ID, id="unsupported-emoji"),
    ],
)
@pytest.mark.anyio
async def test_invalid_reaction_cannot_approve_live_request(
    user_id: int, bot: bool, emoji: str, channel_id: int
) -> None:
    mgr = make_manager(make_settings(timeout_seconds=0.05))
    mgr._ready.set()

    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel

    async def submit_invalid_reaction() -> None:
        await wait_until_pending(mgr, msg)
        channel.id = channel_id
        await mgr._handle_reaction_add(make_fake_reaction(msg, emoji), make_fake_user(user_id, bot=bot))

    reaction_task = asyncio.create_task(submit_invalid_reaction())
    decision = await asyncio.wait_for(mgr.require(make_request()), timeout=2.0)
    await reaction_task

    assert decision == ApprovalDecision.EXPIRED
    msg.edit.assert_awaited_once()
    assert msg.id not in mgr._pending
    embed: discord.Embed = msg.edit.call_args.kwargs["embed"]
    assert "expired" in (embed.title or "")
    assert "timeout" in (next(field.value for field in embed.fields if field.name == "Notes") or "")


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
    embed: discord.Embed = msg.edit.call_args.kwargs["embed"]
    fields = {field.name: field.value for field in embed.fields}
    assert "denied" in (embed.title or "")
    assert fields["Notes"] == "Failed to add reactions."
    assert "Actor" not in fields


@pytest.mark.anyio
async def test_require_keeps_approval_when_message_edit_fails() -> None:
    mgr = make_manager()
    mgr._ready.set()
    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    msg.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Server error"))
    mgr._channel = channel

    async def submit_approval() -> None:
        await wait_until_pending(mgr, msg)
        await mgr._handle_reaction_add(make_fake_reaction(msg, "✅"), make_fake_user(APPROVER_ID))

    reaction_task = asyncio.create_task(submit_approval())
    decision = await asyncio.wait_for(mgr.require(make_request()), timeout=2.0)
    await reaction_task

    assert decision == ApprovalDecision.APPROVED


# ---------------------------------------------------------------------------
# _handle_reaction_add(): authorization and routing logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_conflicting_reactions_keep_first_decision_during_message_edit() -> None:
    mgr = make_manager(make_settings(approver_ids=frozenset({APPROVER_ID, OTHER_USER_ID})))
    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)
    edit_started = asyncio.Event()
    release_edit = asyncio.Event()
    edited_embeds: list[discord.Embed] = []

    async def slow_edit(*, embed: discord.Embed) -> None:
        edited_embeds.append(embed)
        edit_started.set()
        await release_edit.wait()

    msg.edit = AsyncMock(side_effect=slow_edit)
    approve = asyncio.create_task(mgr._handle_reaction_add(make_fake_reaction(msg, "✅"), make_fake_user(APPROVER_ID)))
    await edit_started.wait()
    deny = asyncio.create_task(mgr._handle_reaction_add(make_fake_reaction(msg, "❌"), make_fake_user(OTHER_USER_ID)))
    await asyncio.sleep(0)
    release_edit.set()
    await asyncio.gather(approve, deny)

    assert future.result() == ApprovalDecision.APPROVED
    msg.edit.assert_awaited_once()
    assert "approved" in (edited_embeds[0].title or "")


@pytest.mark.anyio
async def test_require_returns_decision_without_waiting_for_message_edit() -> None:
    mgr = make_manager(make_settings(timeout_seconds=0.05))
    mgr._ready.set()
    channel = make_fake_channel()
    msg = make_fake_message(channel)
    channel.send = AsyncMock(return_value=msg)
    mgr._channel = channel
    edit_started = asyncio.Event()
    release_edit = asyncio.Event()

    async def slow_edit(*, embed: discord.Embed) -> None:
        edit_started.set()
        await release_edit.wait()

    msg.edit = AsyncMock(side_effect=slow_edit)
    require_task = asyncio.create_task(mgr.require(make_request()))
    try:
        await wait_until_pending(mgr, msg)
        reaction_task = asyncio.create_task(
            mgr._handle_reaction_add(make_fake_reaction(msg, "✅"), make_fake_user(APPROVER_ID))
        )
        await edit_started.wait()
        decision = await asyncio.wait_for(require_task, timeout=2)
        release_edit.set()
        await asyncio.wait_for(reaction_task, timeout=2)
    finally:
        release_edit.set()

    assert decision == ApprovalDecision.APPROVED


@pytest.mark.anyio
async def test_approval_client_reaction_event_resolves_pending_approval() -> None:
    mgr = DiscordApprovalManager(make_settings())
    channel = make_fake_channel()
    msg = make_fake_message(channel)
    future = inject_pending(mgr, msg)

    await mgr._client.on_reaction_add(make_fake_reaction(msg, "✅"), make_fake_user(APPROVER_ID))

    assert future.result() == ApprovalDecision.APPROVED
    msg.edit.assert_awaited_once()


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
