from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Mapping, Sequence

import discord

from schwab_mcp.approvals.base import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
)


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DiscordApprovalSettings:
    """Configuration values required for Discord approvals."""

    token: str
    channel_id: int
    approver_ids: frozenset[int] = frozenset()
    timeout_seconds: float = 600.0


@dataclass(slots=True)
class _PendingApproval:
    request: ApprovalRequest
    future: asyncio.Future[ApprovalDecision]
    message: discord.Message


class _ApprovalClient(discord.Client):
    def __init__(
        self, manager: DiscordApprovalManager, intents: discord.Intents
    ) -> None:
        # The base Client expects intents as a keyword-only argument.
        super().__init__(intents=intents)
        self._manager = manager

    async def on_ready(self) -> None:  # pragma: no cover - thin delegation
        await self._manager._handle_ready()

    async def on_reaction_add(  # pragma: no cover - thin delegation
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        await self._manager._handle_reaction_add(reaction, user)


class DiscordApprovalManager(ApprovalManager):
    """Approval manager that routes decisions through Discord reactions."""

    def __init__(self, settings: DiscordApprovalSettings) -> None:
        if not settings.approver_ids:
            raise ValueError(
                "DiscordApprovalManager requires at least one approver ID."
            )

        self._settings = settings
        intents = discord.Intents.default()
        intents.message_content = False
        intents.members = False
        intents.presences = False
        intents.typing = False
        intents.dm_messages = False
        intents.dm_typing = False
        intents.dm_reactions = False

        self._client = _ApprovalClient(self, intents=intents)

        self._runner: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._channel: discord.TextChannel | discord.Thread | None = None
        self._pending: dict[int, _PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._runner is not None:
            return

        loop = asyncio.get_running_loop()
        self._runner = loop.create_task(self._run_client())
        await self._ready.wait()

    async def stop(self) -> None:
        if self._runner is None:
            return

        await self._client.close()
        try:
            await self._runner
        except asyncio.CancelledError:
            pass
        finally:
            self._runner = None
            self._ready.clear()
            self._channel = None

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        await self.start()
        channel = await self._ensure_channel()

        message = await channel.send(embed=self._build_pending_embed(request))
        try:
            await message.add_reaction("✅")
            await message.add_reaction("❌")
        except discord.HTTPException:
            logger.exception(
                "Unable to add approval reactions for request %s", request.id
            )
            await self._finalize_message(
                message,
                request,
                ApprovalDecision.DENIED,
                actor=None,
                reason="Failed to add reactions.",
            )
            return ApprovalDecision.DENIED

        future: asyncio.Future[ApprovalDecision] = (
            asyncio.get_running_loop().create_future()
        )
        pending = _PendingApproval(request=request, future=future, message=message)

        async with self._lock:
            self._pending[message.id] = pending

        try:
            decision = await asyncio.wait_for(
                future, timeout=self._settings.timeout_seconds
            )
        except asyncio.TimeoutError:
            decision = ApprovalDecision.EXPIRED
            await self._finalize_message(
                message,
                request,
                decision,
                actor=None,
                reason=f"No decision within {int(self._settings.timeout_seconds)}s timeout.",
            )
        finally:
            async with self._lock:
                self._pending.pop(message.id, None)

        return decision

    async def _run_client(self) -> None:
        try:
            await self._client.start(self._settings.token)
        except asyncio.CancelledError:
            await self._client.close()
            raise
        except Exception:  # pragma: no cover - propagation for visibility
            logger.exception("Discord approval client stopped unexpectedly")
            raise

    async def _handle_ready(self) -> None:
        logger.info("Discord approval manager connected as %s", self._client.user)
        self._ready.set()

    async def _handle_reaction_add(
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        if user.bot:
            return

        if getattr(reaction.message.channel, "id", None) != self._settings.channel_id:
            return

        async with self._lock:
            pending = self._pending.get(reaction.message.id)

        if pending is None:
            return

        emoji = str(reaction.emoji)
        if emoji not in {"✅", "❌"}:
            return

        if self._settings.approver_ids and user.id not in self._settings.approver_ids:
            logger.debug(
                "Ignoring reaction %s from unauthorized user %s for request %s",
                emoji,
                user.id,
                pending.request.id,
            )
            try:
                await reaction.remove(user)
            except discord.HTTPException:
                logger.warning(
                    "Failed to remove unauthorized reaction from user %s", user.id
                )
            return

        decision = (
            ApprovalDecision.APPROVED if emoji == "✅" else ApprovalDecision.DENIED
        )

        if pending.future.done():
            return

        await self._finalize_message(
            pending.message,
            pending.request,
            decision,
            actor=user,
            reason=f"Decision recorded via {emoji}",
        )
        pending.future.set_result(decision)

    async def _ensure_channel(self) -> discord.abc.MessageableChannel:
        await self._ready.wait()
        if self._channel is not None:
            return self._channel

        channel = self._client.get_channel(self._settings.channel_id)
        if channel is None:
            fetched = await self._client.fetch_channel(self._settings.channel_id)
            if not isinstance(fetched, (discord.TextChannel, discord.Thread)):
                raise RuntimeError("Configured Discord channel is not messageable")
            channel = fetched

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise RuntimeError("Configured Discord channel is not messageable")

        self._channel = channel
        return channel

    def _build_pending_embed(self, request: ApprovalRequest) -> discord.Embed:
        embed = discord.Embed(
            title="Write operation requires approval",
            description=f"Tool `{request.tool_name}` requested write access.",
            colour=discord.Colour.orange(),
        )
        embed.add_field(name="Request ID", value=request.request_id, inline=False)
        embed.add_field(name="Approval ID", value=request.id, inline=False)
        if request.client_id:
            embed.add_field(name="Client ID", value=request.client_id, inline=False)
        if request.arguments:
            embed.add_field(
                name="Arguments",
                value=self._format_arguments(request.arguments),
                inline=False,
            )
        embed.set_footer(text="React with ✅ to approve or ❌ to deny.")
        return embed

    async def _finalize_message(
        self,
        message: discord.Message,
        request: ApprovalRequest,
        decision: ApprovalDecision,
        *,
        actor: discord.abc.User | None,
        reason: str | None,
    ) -> None:
        embed = discord.Embed(
            title=f"Write operation {decision.value}",
            description=f"Tool `{request.tool_name}` request {decision.value}.",
            colour=self._colour_for_decision(decision),
        )
        embed.add_field(name="Request ID", value=request.request_id, inline=False)
        embed.add_field(name="Approval ID", value=request.id, inline=False)
        if request.client_id:
            embed.add_field(name="Client ID", value=request.client_id, inline=False)
        if request.arguments:
            embed.add_field(
                name="Arguments",
                value=self._format_arguments(request.arguments),
                inline=False,
            )
        if actor is not None:
            embed.add_field(
                name="Actor", value=f"{actor} (ID: {actor.id})", inline=False
            )
        if reason:
            embed.add_field(name="Notes", value=reason, inline=False)
        try:
            await message.edit(embed=embed)
        except discord.HTTPException:
            logger.warning(
                "Failed to update Discord approval message for request %s", request.id
            )

    @staticmethod
    def _format_arguments(arguments: Mapping[str, str]) -> str:
        if not arguments:
            return "`<none>`"

        lines: list[str] = []
        for key, value in arguments.items():
            lines.append(f"`{key}` = {value}")
        rendered = "\n".join(lines)
        if len(rendered) > 1000:
            return f"{rendered[:997]}..."
        return rendered

    @staticmethod
    def _colour_for_decision(decision: ApprovalDecision) -> discord.Colour:
        match decision:
            case ApprovalDecision.APPROVED:
                return discord.Colour.brand_green()
            case ApprovalDecision.DENIED:
                return discord.Colour.red()
            case ApprovalDecision.EXPIRED:
                return discord.Colour.dark_grey()

    @staticmethod
    def authorized_user_ids(users: Sequence[int] | None) -> frozenset[int]:
        """Normalize a sequence of authorized Discord user IDs."""
        if not users:
            return frozenset()
        return frozenset(int(user) for user in users)


__all__ = ["DiscordApprovalManager", "DiscordApprovalSettings"]
