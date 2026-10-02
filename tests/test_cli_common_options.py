from __future__ import annotations

from typing import Any

import pytest

from schwab_mcp import cli


@pytest.mark.parametrize("command", ["auth", "server"])
def test_shared_options_are_listed_in_command_help(cli_runner, command: str) -> None:
    """Both commands expose the shared credential and URL options."""
    result = cli_runner.invoke(cli.cli, [command, "--help"])

    assert result.exit_code == 0
    for option in ("--client-id", "--client-secret", "--callback-url", "--base-url", "--token-path"):
        assert option in result.output


@pytest.mark.parametrize(
    ("command", "capture_fixture"),
    [("auth", "cli_auth_capture"), ("server", "cli_server_capture")],
)
def test_shared_url_defaults_are_forwarded(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    cli_runner,
    cli_credentials_file,
    command: str,
    capture_fixture: str,
) -> None:
    """Authentication and server use the documented default Schwab URLs."""
    captured: dict[str, Any] = request.getfixturevalue(capture_fixture)
    monkeypatch.delenv("SCHWAB_CALLBACK_URL", raising=False)
    monkeypatch.delenv("SCHWAB_BASE_URL", raising=False)
    args = [command, "--client-id", "test-id", "--client-secret", "test-secret"]
    if command == "server":
        args.append("--jesus-take-the-wheel")

    result = cli_runner.invoke(cli.cli, args)

    assert result.exit_code == 0
    kwargs = captured["easy_client_kwargs"]
    assert kwargs["callback_url"] == "https://127.0.0.1:8182"
    assert kwargs["base_url"] == "https://api.schwabapi.com"


@pytest.mark.parametrize(
    ("command", "capture_fixture"),
    [("auth", "cli_auth_capture"), ("server", "cli_server_capture")],
)
def test_environment_options_are_forwarded(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    cli_runner,
    cli_credentials_file,
    command: str,
    capture_fixture: str,
) -> None:
    """Both commands forward credentials and URLs supplied through the environment."""
    captured: dict[str, Any] = request.getfixturevalue(capture_fixture)
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "environment-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "environment-secret")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:9191")
    monkeypatch.setenv("SCHWAB_BASE_URL", "https://example.test/api")
    args = [command]
    if command == "server":
        args.append("--jesus-take-the-wheel")

    result = cli_runner.invoke(cli.cli, args)

    assert result.exit_code == 0
    kwargs = captured["easy_client_kwargs"]
    assert kwargs["client_id"] == "environment-id"
    assert kwargs["client_secret"] == "environment-secret"
    assert kwargs["callback_url"] == "https://127.0.0.1:9191"
    assert kwargs["base_url"] == "https://example.test/api"


@pytest.mark.parametrize(
    ("command", "capture_fixture"),
    [("auth", "cli_auth_capture"), ("server", "cli_server_capture")],
)
def test_explicit_options_override_environment(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    cli_runner,
    cli_credentials_file,
    command: str,
    capture_fixture: str,
) -> None:
    """Explicit flags take priority over environment-provided values."""
    captured: dict[str, Any] = request.getfixturevalue(capture_fixture)
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "environment-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "environment-secret")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:9191")
    monkeypatch.setenv("SCHWAB_BASE_URL", "https://example.test/api")
    args = [
        command,
        "--client-id",
        "explicit-id",
        "--client-secret",
        "explicit-secret",
        "--callback-url",
        "https://127.0.0.1:8282",
        "--base-url",
        "https://api.example.test",
    ]
    if command == "server":
        args.append("--jesus-take-the-wheel")

    result = cli_runner.invoke(cli.cli, args)

    assert result.exit_code == 0
    kwargs = captured["easy_client_kwargs"]
    assert kwargs["client_id"] == "explicit-id"
    assert kwargs["client_secret"] == "explicit-secret"
    assert kwargs["callback_url"] == "https://127.0.0.1:8282"
    assert kwargs["base_url"] == "https://api.example.test"
