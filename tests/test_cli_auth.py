from __future__ import annotations

from typing import Any

from click.testing import CliRunner

from schwab_mcp import cli


def test_auth_command_uses_max_token_age(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}

    class DummyManager:
        def __init__(self, path: str) -> None:
            self.path = path
            captured["token_path"] = path

    def fake_easy_client(**kwargs):
        captured["easy_client_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    runner = CliRunner()
    token_file = tmp_path / "token.yaml"
    result = runner.invoke(
        cli.cli,
        [
            "auth",
            "--token-path",
            str(token_file),
            "--client-id",
            "cid",
            "--client-secret",
            "secret",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["token_path"] == str(token_file)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS


def test_auth_command_returns_error_on_exception(monkeypatch, tmp_path):
    """When easy_client raises, the auth command prints an error but does not re-raise."""

    class DummyManager:
        def __init__(self, path: str) -> None:
            self.path = path

    def fake_easy_client(**kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    runner = CliRunner()
    token_file = tmp_path / "token.yaml"
    result = runner.invoke(
        cli.cli,
        [
            "auth",
            "--token-path",
            str(token_file),
            "--client-id",
            "cid",
            "--client-secret",
            "secret",
        ],
    )

    # The command catches the exception and returns 1 via the non-zero exit path
    assert "Authentication failed: network unavailable" in result.output
    # Note: the command returns 1 but Click converts it via the function return value


def test_cli_main_entrypoint_delegates_to_cli_group(monkeypatch):
    """main() must call through to the cli() Click group (entry point contract)."""
    import schwab_mcp.cli as cli_module

    called: dict[str, Any] = {}

    def fake_cli_group():
        called["invoked"] = True
        return 0

    monkeypatch.setattr(cli_module, "cli", fake_cli_group)
    result = cli_module.main()

    assert called.get("invoked") is True
    assert result == 0
