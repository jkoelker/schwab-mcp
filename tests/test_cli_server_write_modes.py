from __future__ import annotations

from typing import Any

from click.testing import CliRunner
from schwab.client import AsyncClient

from schwab_mcp import cli
from schwab_mcp.approvals import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    NoOpApprovalManager,
)


class FakeAsyncClient:
    def token_age(self) -> int:
        return 0

    async def close_async_session(self) -> None:
        return None


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


def _patch_common(monkeypatch, captured: dict[str, Any]) -> None:
    monkeypatch.setattr(cli, "AsyncClient", FakeAsyncClient)

    def fake_easy_client(**_kwargs):
        captured["easy_client_called"] = True
        captured["easy_client_kwargs"] = _kwargs
        return FakeAsyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    class FakeServer:
        def __init__(
            self,
            name,
            client,
            approval_manager,
            *,
            allow_write,
            enable_technical_tools=True,
            use_json=False,
        ):
            captured["server_name"] = name
            captured["server_client"] = client
            captured["approval_manager"] = approval_manager
            captured["allow_write"] = allow_write
            captured["enable_technical_tools"] = enable_technical_tools
            captured["use_json"] = use_json

        async def run(self):
            captured["run_called"] = True

    monkeypatch.setattr(cli, "SchwabMCPServer", FakeServer)
    monkeypatch.setattr(
        cli.anyio,
        "run",
        lambda func, *args, backend="asyncio", **kwargs: (
            captured.setdefault("anyio_backend", backend),
            captured.setdefault("anyio_args", args),
            captured.setdefault("anyio_kwargs", kwargs),
        ),
    )


def test_server_defaults_to_read_only(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_enables_write_mode_when_flag_set(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_enables_write_mode_with_discord(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_json_flag_enables_json_output(monkeypatch):
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_with_error_when_credentials_missing(monkeypatch, tmp_path):
    """server command calls send_error_response and exits 1 when creds are absent."""

    creds_path = tmp_path / "nonexistent.yaml"
    monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
    monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["server", "--token-path", str(tmp_path / "token.yaml")],
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Non-async client / client init exception paths
# ---------------------------------------------------------------------------


def test_server_exits_when_easy_client_raises(monkeypatch):
    """When easy_client raises, server sends a 500 error response and exits 1."""
    monkeypatch.setattr(cli, "AsyncClient", FakeAsyncClient)

    def boom_easy_client(**_kwargs):
        raise RuntimeError("auth exploded")

    monkeypatch.setattr(cli.schwab_auth, "easy_client", boom_easy_client)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_client_is_not_async(monkeypatch):
    """When easy_client returns a non-AsyncClient, server sends a 500 error and exits 1."""

    class SyncClient:
        """A fake non-async client."""

    # Make isinstance(client, AsyncClient) return False by patching AsyncClient
    # to a type the SyncClient does NOT inherit from.
    monkeypatch.setattr(cli, "AsyncClient", AsyncClient)

    def sync_easy_client(**_kwargs):
        return SyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", sync_easy_client)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_token_is_too_old(monkeypatch):
    """When the token is older than the max age, server sends a 401 error and exits 1."""

    class StaleAsyncClient(FakeAsyncClient):
        def token_age(self) -> int:
            return cli.TOKEN_MAX_AGE_SECONDS + 1  # expired

    monkeypatch.setattr(cli, "AsyncClient", StaleAsyncClient)

    def fake_easy_client(**_kwargs):
        return StaleAsyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["server", "--client-id", "client", "--client-secret", "secret"],
    )

    assert result.exit_code == 1
    assert "Token is older than 5 days" in result.output


# ---------------------------------------------------------------------------
# SCHWAB_MCP_DISCORD_APPROVERS env var parsing
# ---------------------------------------------------------------------------


def test_server_reads_approvers_from_env_var(monkeypatch):
    """SCHWAB_MCP_DISCORD_APPROVERS env var is parsed as a comma-separated list."""
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)
    monkeypatch.setenv("SCHWAB_MCP_DISCORD_APPROVERS", "111, 222, 333")

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_discord_token_missing(monkeypatch):
    """Discord channel provided but no token → error exit."""
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_discord_channel_missing(monkeypatch):
    """Discord token provided but no channel ID → error exit."""
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_approver_list_empty(monkeypatch):
    """Discord token + channel but empty approver list → error exit."""
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)
    monkeypatch.setattr(cli, "DiscordApprovalManager", DummyDiscordApprovalManager)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_warns_when_jesus_flag_and_discord_token_both_set(monkeypatch):
    """--jesus-take-the-wheel with a Discord token emits a bypass warning."""
    captured: dict[str, Any] = {}
    _patch_common(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
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


def test_server_exits_when_server_run_raises(monkeypatch):
    """When SchwabMCPServer.run() raises, CLI sends a 500 error response and exits 1."""
    monkeypatch.setattr(cli, "AsyncClient", FakeAsyncClient)

    def fake_easy_client(**_kwargs):
        return FakeAsyncClient()

    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    def fake_run(func, *args, backend="asyncio", **kwargs):
        raise RuntimeError("server exploded during run")

    monkeypatch.setattr(cli.anyio, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        ["server", "--client-id", "client", "--client-secret", "secret"],
    )

    assert result.exit_code == 1
    assert "server exploded during run" in result.output
