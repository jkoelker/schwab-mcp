from __future__ import annotations

import os
from typing import Any

import yaml
from click.testing import CliRunner

from schwab_mcp import cli


class FakeAsyncClient:
    def token_age(self) -> int:
        return 0

    async def close_async_session(self) -> None:
        return None


def _patch_auth(monkeypatch, captured: dict[str, Any]) -> None:
    class DummyManager:
        def __init__(self, path: str) -> None:
            self.path = path

    def fake_easy_client(**kwargs):
        captured["easy_client_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)


class TestAuthCredentialsFile:
    def test_falls_back_to_credentials_file(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}
        _patch_auth(monkeypatch, captured)

        creds_path = tmp_path / "credentials.yaml"
        with open(creds_path, "w") as f:
            yaml.safe_dump({"client_id": "file-id", "client_secret": "file-secret"}, f)

        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            ["auth", "--token-path", str(tmp_path / "token.yaml")],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "file-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "file-secret"

    def test_cli_args_override_credentials_file(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}
        _patch_auth(monkeypatch, captured)

        creds_path = tmp_path / "credentials.yaml"
        with open(creds_path, "w") as f:
            yaml.safe_dump({"client_id": "file-id", "client_secret": "file-secret"}, f)

        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "auth",
                "--token-path",
                str(tmp_path / "token.yaml"),
                "--client-id",
                "cli-id",
                "--client-secret",
                "cli-secret",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "cli-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "cli-secret"

    def test_errors_when_no_credentials_available(self, monkeypatch, tmp_path):
        _patch_auth(monkeypatch, {})

        creds_path = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ["auth", "--token-path", str(tmp_path / "t.yaml")]
        )

        assert result.exit_code == 1
        assert "client-id and client-secret are required" in result.output


class TestServerCredentialsFile:
    def _patch_server(self, monkeypatch, captured: dict[str, Any]) -> None:
        monkeypatch.setattr(cli, "AsyncClient", FakeAsyncClient)

        def fake_easy_client(**kwargs):
            captured["easy_client_kwargs"] = kwargs
            return FakeAsyncClient()

        monkeypatch.setattr(
            cli.tokens, "Manager", lambda p: type("M", (), {"path": p})()
        )
        monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)
        monkeypatch.setattr(
            cli,
            "SchwabMCPServer",
            lambda *a, **kw: type("S", (), {"run": staticmethod(lambda: None)})(),
        )
        monkeypatch.setattr(cli.anyio, "run", lambda func, **kw: None)

    def test_falls_back_to_credentials_file(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}
        self._patch_server(monkeypatch, captured)

        creds_path = tmp_path / "credentials.yaml"
        with open(creds_path, "w") as f:
            yaml.safe_dump({"client_id": "file-id", "client_secret": "file-secret"}, f)

        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "server",
                "--token-path",
                str(tmp_path / "token.yaml"),
                "--jesus-take-the-wheel",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "file-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "file-secret"

    def test_cli_args_override_credentials_file(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}
        self._patch_server(monkeypatch, captured)

        creds_path = tmp_path / "credentials.yaml"
        with open(creds_path, "w") as f:
            yaml.safe_dump({"client_id": "file-id", "client_secret": "file-secret"}, f)

        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "server",
                "--token-path",
                str(tmp_path / "token.yaml"),
                "--client-id",
                "cli-id",
                "--client-secret",
                "cli-secret",
                "--jesus-take-the-wheel",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "cli-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "cli-secret"

    def test_errors_when_no_credentials_available(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}
        self._patch_server(monkeypatch, captured)

        creds_path = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))
        monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
        monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli, ["server", "--token-path", str(tmp_path / "t.yaml")]
        )

        assert result.exit_code == 1


class TestSaveCredentialsCommand:
    def test_saves_credentials_with_prompts(self, monkeypatch, tmp_path):
        creds_path = tmp_path / "credentials.yaml"
        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            ["save-credentials"],
            input="my-client-id\nmy-client-secret\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Credentials saved to:" in result.output

        with open(creds_path) as f:
            data = yaml.safe_load(f)

        assert data == {
            "client_id": "my-client-id",
            "client_secret": "my-client-secret",
        }

    def test_saves_credentials_with_flags(self, monkeypatch, tmp_path):
        creds_path = tmp_path / "credentials.yaml"
        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "save-credentials",
                "--client-id",
                "flag-id",
                "--client-secret",
                "flag-secret",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0

        with open(creds_path) as f:
            data = yaml.safe_load(f)

        assert data == {"client_id": "flag-id", "client_secret": "flag-secret"}

    def test_file_has_restricted_permissions(self, monkeypatch, tmp_path):
        creds_path = tmp_path / "credentials.yaml"
        monkeypatch.setattr(cli.tokens, "credentials_path", lambda app: str(creds_path))

        runner = CliRunner()
        runner.invoke(
            cli.cli,
            ["save-credentials", "--client-id", "id", "--client-secret", "secret"],
            catch_exceptions=False,
        )

        mode = os.stat(creds_path).st_mode & 0o777
        assert mode == 0o600
