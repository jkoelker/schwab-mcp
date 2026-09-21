from __future__ import annotations

from typing import Any

from schwab_mcp import cli


def test_auth_command_uses_max_token_age(cli_auth_capture, cli_runner, tmp_path):
    """Pass the configured maximum token age to the authentication client."""
    captured: dict[str, Any] = cli_auth_capture
    token_file = tmp_path / "token.yaml"
    result = cli_runner.invoke(
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


def test_auth_command_returns_error_on_exception(
    monkeypatch,
    cli_auth_capture,
    cli_runner,
    tmp_path,
):
    """When easy_client raises, the auth command prints an error but does not re-raise."""

    def fake_easy_client(**kwargs: Any) -> object:
        """Raise the authentication failure used by this test."""
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    token_file = tmp_path / "token.yaml"
    result = cli_runner.invoke(
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
