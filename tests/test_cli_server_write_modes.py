from __future__ import annotations

from schwab.client import AsyncClient

from schwab_mcp import cli
from schwab_mcp.approvals import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    NoOpApprovalManager,
)


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
