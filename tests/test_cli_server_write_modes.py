from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

import discord
import pytest
from schwab.client import AsyncClient

from schwab_mcp import cli
from schwab_mcp.approvals import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    NoOpApprovalManager,
)
from schwab_mcp.server import MCPServer, SchwabMCPServer


class DummyDiscordApprovalManager(ApprovalManager):
    def __init__(self, settings) -> None:
        self.settings = settings

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    @staticmethod
    def authorized_user_ids(users):
        if not users:
            return frozenset()
        return frozenset(int(value) for value in users)


def test_server_defaults_to_read_only(cli_server_capture, cli_runner):
    """Start the server in read-only mode by default."""
    captured = cli_server_capture
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["allow_write"] is False
    assert isinstance(captured["approval_manager"], NoOpApprovalManager)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS
    assert captured["use_json"] is False


def test_server_enables_write_mode_when_flag_set(cli_server_capture, cli_runner):
    """Enable write mode when the bypass flag is supplied."""
    captured = cli_server_capture
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--jesus-take-the-wheel",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["allow_write"] is True
    assert isinstance(captured["approval_manager"], NoOpApprovalManager)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS
    assert captured["use_json"] is False


def test_server_enables_write_mode_with_discord(monkeypatch, cli_server_capture, cli_runner):
    """Enable write mode when Discord approval is configured."""
    captured = cli_server_capture
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)

    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--discord-token",
            "token",
            "--discord-channel-id",
            "123",
            "--discord-approver",
            "456",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["allow_write"] is True
    assert isinstance(captured["approval_manager"], DummyDiscordApprovalManager)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS
    assert captured["use_json"] is False


def test_server_json_flag_enables_json_output(cli_server_capture, cli_runner):
    """Pass the JSON output flag to the MCP server."""
    captured = cli_server_capture
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["use_json"] is True


# ---------------------------------------------------------------------------
# Missing-credentials path for the server command
# ---------------------------------------------------------------------------


def test_server_exits_with_error_when_credentials_missing(cli_runner, cli_credentials_file):
    """server command calls send_error_response and exits 1 when creds are absent."""
    result = cli_runner.invoke(
        cli.cli,
        ["server", "--token-path", str(cli_credentials_file.with_name("token.yaml"))],
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Non-async client / client init exception paths
# ---------------------------------------------------------------------------


def test_server_exits_when_easy_client_raises(monkeypatch, cli_async_client_type, cli_runner):
    """When easy_client raises, server sends a 500 error response and exits 1."""
    monkeypatch.setattr(cli, "AsyncClient", cli_async_client_type)

    def boom_easy_client(**_kwargs):
        """Raise the client initialization failure used by this test."""
        raise RuntimeError("auth exploded")

    monkeypatch.setattr(cli.schwab_auth, "easy_client", boom_easy_client)

    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert result.exit_code == 1
    assert "auth exploded" in result.output


def test_server_exits_when_client_is_not_async(monkeypatch, cli_runner):
    """When easy_client returns a non-AsyncClient, server sends a 500 error and exits 1."""

    class SyncClient:
        """A fake non-async client."""

    # Make isinstance(client, AsyncClient) return False by patching AsyncClient
    # to a type the SyncClient does NOT inherit from.
    monkeypatch.setattr(cli, "AsyncClient", AsyncClient)

    def sync_easy_client(**_kwargs):
        """Return a synchronous client to exercise the type guard."""
        return SyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", sync_easy_client)

    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert result.exit_code == 1
    assert "Async client required" in result.output


# ---------------------------------------------------------------------------
# Token age expiry
# ---------------------------------------------------------------------------


def test_server_exits_when_token_is_too_old(monkeypatch, cli_async_client_type, cli_runner):
    """When the token is older than the max age, server sends a 401 error and exits 1."""

    class StaleAsyncClient(cli_async_client_type):
        """Fake async client with an expired token."""

        def token_age(self) -> int:
            """Return a token age beyond the configured maximum."""
            return cli.TOKEN_MAX_AGE_SECONDS + 1  # expired

    monkeypatch.setattr(cli, "AsyncClient", StaleAsyncClient)

    def fake_easy_client(**_kwargs):
        """Return a client with an expired token."""
        return StaleAsyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    result = cli_runner.invoke(
        cli.cli,
        ["server", "--client-id", "client", "--client-secret", "secret"],
    )

    assert result.exit_code == 1
    assert "Token is older than 5 days" in result.output


# ---------------------------------------------------------------------------
# SCHWAB_MCP_DISCORD_APPROVERS env var parsing
# ---------------------------------------------------------------------------


def test_server_reads_approvers_from_env_var(monkeypatch, cli_server_capture, cli_runner):
    """SCHWAB_MCP_DISCORD_APPROVERS env var is parsed as a comma-separated list."""
    captured = cli_server_capture
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_APPROVERS", "111, 222, 333")

    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--discord-token",
            "tok",
            "--discord-channel-id",
            "999",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["allow_write"] is True
    manager = captured["approval_manager"]
    assert isinstance(manager, DummyDiscordApprovalManager)
    assert manager.settings.approver_ids == frozenset({111, 222, 333})


# ---------------------------------------------------------------------------
# Missing Discord token/channel
# ---------------------------------------------------------------------------


def test_server_exits_when_discord_token_missing(monkeypatch, cli_server_capture, cli_runner):
    """Discord channel provided but no token → error exit."""
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--discord-channel-id",
            "123",
            "--discord-approver",
            "456",
        ],
    )

    assert result.exit_code == 1
    assert "Discord approval configuration is required" in result.output


def test_server_exits_when_discord_channel_missing(monkeypatch, cli_server_capture, cli_runner):
    """Discord token provided but no channel ID → error exit."""
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--discord-token",
            "tok",
            "--discord-approver",
            "456",
        ],
    )

    assert result.exit_code == 1
    assert "Discord approval configuration is required" in result.output


# ---------------------------------------------------------------------------
# Empty approver list
# ---------------------------------------------------------------------------


def test_server_exits_when_approver_list_empty(monkeypatch, cli_server_capture, cli_runner):
    """Discord token + channel but empty approver list → error exit."""
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)

    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--discord-token",
            "tok",
            "--discord-channel-id",
            "123",
            # no --discord-approver and no env var → empty frozenset
        ],
    )

    assert result.exit_code == 1
    assert "approver list cannot be empty" in result.output


# ---------------------------------------------------------------------------
# --jesus-take-the-wheel + discord token warning
# ---------------------------------------------------------------------------


def test_server_warns_when_jesus_flag_and_discord_token_both_set(
    monkeypatch,
    cli_server_capture,
    cli_runner,
):
    """--jesus-take-the-wheel with a Discord token emits a bypass warning."""
    result = cli_runner.invoke(
        cli.cli,
        [
            "server",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
            "--jesus-take-the-wheel",
            "--discord-token",
            "tok",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    # Warning goes to stderr
    assert "bypasses Discord approvals" in (result.output + (result.stderr or ""))


# ---------------------------------------------------------------------------
# Server run exception handling
# ---------------------------------------------------------------------------


def test_server_exits_when_server_run_raises(monkeypatch, cli_server_capture, cli_runner):
    """When SchwabMCPServer.run() raises, CLI sends a 500 error response and exits 1."""

    def fake_run(func, *args, backend="asyncio", **kwargs):
        """Raise the server runtime failure used by this test."""
        raise RuntimeError("server exploded during run")

    monkeypatch.setattr(cli.anyio, "run", fake_run)

    result = cli_runner.invoke(
        cli.cli,
        ["server", "--client-id", "client", "--client-secret", "secret"],
    )

    assert result.exit_code == 1
    assert "server exploded during run" in result.output


@pytest.fixture
def isolated_server_cli_environment(monkeypatch, tmp_path: Path) -> Path:
    """Keep platform directories and CLI configuration inside this test."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    for name in (
        "SCHWAB_CLIENT_ID",
        "SCHWAB_CLIENT_SECRET",
        "SCHWAB_CALLBACK_URL",
        "SCHWAB_BASE_URL",
        "SCHWAB_MCP_DISCORD_TOKEN",
        "SCHWAB_MCP_DISCORD_CHANNEL_ID",
        "SCHWAB_MCP_DISCORD_APPROVERS",
        "SCHWAB_MCP_DISCORD_TIMEOUT",
        "MCP_HOST",
        "MCP_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "token.yaml"


@pytest.fixture
def sociable_cli_server(monkeypatch) -> dict[str, Any]:
    """Fake Schwab initialization and transport around the real MCP server."""
    captured: dict[str, Any] = {}

    class StartupClient:
        def token_age(self) -> int:
            return 0

    client = StartupClient()

    def fake_easy_client(**kwargs: Any) -> StartupClient:
        captured["easy_client_kwargs"] = kwargs
        return client

    monkeypatch.setattr(cli, "AsyncClient", StartupClient)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    real_server_type = cli.SchwabMCPServer

    def construct_real_server(
        name: str,
        schwab_client: Any,
        approval_manager: ApprovalManager,
        *,
        allow_write: bool,
        enable_technical_tools: bool = True,
        use_json: bool = False,
    ) -> SchwabMCPServer:
        server = real_server_type(
            name,
            schwab_client,
            approval_manager=approval_manager,
            allow_write=allow_write,
            enable_technical_tools=enable_technical_tools,
            use_json=use_json,
        )
        captured["server"] = server
        captured["approval_manager"] = approval_manager
        captured["allow_write"] = allow_write
        return server

    monkeypatch.setattr(cli, "SchwabMCPServer", construct_real_server)

    async def fake_run_stdio_async(server: MCPServer) -> None:
        captured["transport"] = "stdio"
        captured["registered_tools"] = {tool.name for tool in await server.list_tools()}

    async def fake_run_streamable_http_async(server: MCPServer, *, host: str, port: int) -> None:
        captured["transport"] = "streamable-http"
        captured["host"] = host
        captured["port"] = port
        captured["registered_tools"] = {tool.name for tool in await server.list_tools()}

    monkeypatch.setattr(MCPServer, "run_stdio_async", fake_run_stdio_async)
    monkeypatch.setattr(MCPServer, "run_streamable_http_async", fake_run_streamable_http_async)
    return captured


def _server_args(token_path: Path, *options: str) -> list[str]:
    return [
        "server",
        "--token-path",
        str(token_path),
        "--client-id",
        "cli-client-id",
        "--client-secret",
        "cli-client-secret",
        "--json",
        "--no-technical-tools",
        *options,
    ]


def _approval_request() -> ApprovalRequest:
    return ApprovalRequest(
        id="approval-1",
        tool_name="cancel_order",
        request_id="request-1",
        client_id=None,
        arguments={"order_id": "123"},
    )


def test_cli_server_default_is_read_only_with_real_policy_and_manager(
    cli_runner,
    isolated_server_cli_environment,
    sociable_cli_server,
) -> None:
    token_path = isolated_server_cli_environment
    captured = sociable_cli_server

    result = cli_runner.invoke(cli.cli, _server_args(token_path), catch_exceptions=False)

    assert result.exit_code == 0
    assert captured["allow_write"] is False
    assert captured["transport"] == "stdio"
    assert "preview_equity_order" in captured["registered_tools"]
    assert "cancel_order" not in captured["registered_tools"]
    assert "place_previewed_order" not in captured["registered_tools"]

    token_manager = captured["easy_client_kwargs"]["token_manager"]
    assert token_manager.path == str(token_path)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS


def test_cli_server_bypass_enables_writes_even_with_incomplete_discord_config(
    cli_runner,
    isolated_server_cli_environment,
    sociable_cli_server,
) -> None:
    token_path = isolated_server_cli_environment
    captured = sociable_cli_server

    result = cli_runner.invoke(
        cli.cli,
        _server_args(
            token_path,
            "--jesus-take-the-wheel",
            "--discord-channel-id",
            "777",
            "--discord-approver",
            "456",
        ),
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["allow_write"] is True
    assert {"cancel_order", "place_previewed_order"} <= captured["registered_tools"]
    assert asyncio.run(captured["approval_manager"].require(_approval_request())) is ApprovalDecision.APPROVED
    assert "Discord approval configuration is required" not in result.output


class _FakeDiscordMessage:
    def __init__(self, channel: _FakeDiscordTextChannel, embed: discord.Embed) -> None:
        self.id = 9001
        self.channel = channel
        self.embed = embed

    async def add_reaction(self, _emoji: str) -> None:
        return None


class _FakeDiscordTextChannel(discord.TextChannel):
    __slots__ = ("channel_id", "message", "message_sent")

    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.message: _FakeDiscordMessage | None = None
        self.message_sent = asyncio.Event()

    @property
    def id(self) -> int:
        return self.channel_id

    async def send(self, *, embed: discord.Embed) -> _FakeDiscordMessage:
        self.message = _FakeDiscordMessage(self, embed)
        self.message_sent.set()
        return self.message


@pytest.fixture
def fake_discord_network(monkeypatch) -> dict[str, Any]:
    """Replace Discord network methods while retaining its real client adapter."""
    captured: dict[str, Any] = {"tokens": [], "channel_ids": []}
    channel = _FakeDiscordTextChannel(channel_id=789)

    async def fake_start(client: Any, token: str) -> None:
        captured["tokens"].append(token)
        await client.on_ready()

    async def fake_close(_client: discord.Client) -> None:
        return None

    def fake_get_channel(_client: discord.Client, channel_id: int) -> _FakeDiscordTextChannel:
        captured["channel_ids"].append(channel_id)
        return channel

    monkeypatch.setattr(discord.Client, "start", fake_start)
    monkeypatch.setattr(discord.Client, "close", fake_close)
    monkeypatch.setattr(discord.Client, "get_channel", fake_get_channel)
    captured["channel"] = channel
    return captured


def test_cli_server_uses_complete_discord_configuration_and_real_approval_manager(
    monkeypatch,
    cli_runner,
    isolated_server_cli_environment,
    sociable_cli_server,
    fake_discord_network,
) -> None:
    token_path = isolated_server_cli_environment
    captured = sociable_cli_server
    discord_network = fake_discord_network
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_TOKEN", "discord-env-token")
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_CHANNEL_ID", "789")
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_APPROVERS", " 456, 789 ")
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_TIMEOUT", "15")

    result = cli_runner.invoke(cli.cli, _server_args(token_path), catch_exceptions=False)

    assert result.exit_code == 0
    assert captured["allow_write"] is True
    assert {"cancel_order", "place_previewed_order"} <= captured["registered_tools"]
    assert captured["transport"] == "stdio"

    async def observe_pending_approval() -> None:
        manager = captured["approval_manager"]
        request_task = asyncio.create_task(manager.require(_approval_request()))
        try:
            await asyncio.wait_for(discord_network["channel"].message_sent.wait(), timeout=2)
            message = discord_network["channel"].message
            assert message is not None
            assert message.embed.title == "Write operation requires approval"
            assert not request_task.done()
        finally:
            if not request_task.done():
                request_task.cancel()
                with suppress(asyncio.CancelledError):
                    await request_task
            await captured["approval_manager"].stop()

    asyncio.run(observe_pending_approval())
    assert discord_network["tokens"] == ["discord-env-token"]
    assert discord_network["channel_ids"] == [789]


@pytest.mark.parametrize(
    ("discord_options", "expected_message", "expected_details"),
    [
        (
            ["--discord-channel-id", "789", "--discord-approver", "456"],
            "Discord approval configuration is required to enable write tools.",
            {"missing_token": True, "missing_channel_id": False},
        ),
        (
            ["--discord-token", "discord-token", "--discord-channel-id", "789"],
            "Discord approver list cannot be empty. Configure at least one reviewer.",
            {"approver_source": "flags_or_env"},
        ),
    ],
)
def test_cli_server_rejects_incomplete_discord_config_with_mcp_error_before_transport(
    cli_runner,
    isolated_server_cli_environment,
    sociable_cli_server,
    discord_options: list[str],
    expected_message: str,
    expected_details: dict[str, Any],
) -> None:
    token_path = isolated_server_cli_environment
    captured = sociable_cli_server

    result = cli_runner.invoke(cli.cli, _server_args(token_path, *discord_options))

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == 400
    assert payload["error"]["message"] == expected_message
    assert payload["error"]["data"] == expected_details
    assert "server" not in captured
    assert "transport" not in captured
