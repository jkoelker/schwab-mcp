from __future__ import annotations

from click.testing import CliRunner
from typing import Any

from schwab_mcp import cli
from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest, NoOpApprovalManager


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
        def __init__(self, name, client, approval_manager, *, allow_write):
            captured["server_name"] = name
            captured["server_client"] = client
            captured["approval_manager"] = approval_manager
            captured["allow_write"] = allow_write

        async def run(self):
            captured["run_called"] = True

    monkeypatch.setattr(cli, "SchwabMCPServer", FakeServer)
    monkeypatch.setattr(cli.anyio, "run", lambda func, backend="asyncio": captured.setdefault("anyio_backend", backend))


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
