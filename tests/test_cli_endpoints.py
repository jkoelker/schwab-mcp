"""The CLI refuses endpoints that would expose the server or its secrets."""

from __future__ import annotations

from typing import Any

import pytest
from schwab.client import AsyncClient

from schwab_mcp import cli
from schwab_mcp.server import SchwabMCPServer

ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the bind under test
BASE = ["server", "--client-id", "client", "--client-secret", "secret"]
SIGNAL = ["--signal-account", "+15555550100", "--signal-approver", "+15555550199"]


def _invoke(cli_runner, args: list[str]) -> Any:
    return cli_runner.invoke(cli.cli, args, catch_exceptions=False)


@pytest.mark.parametrize("host", [ALL_INTERFACES, "192.168.1.10", "::", "example.com"])
def test_http_refuses_non_loopback_host(cli_server_capture, cli_runner, host: str) -> None:
    result = _invoke(cli_runner, [*BASE, "--http", "--host", host])

    assert result.exit_code != 0
    assert "authenticating" in result.output
    assert "server_name" not in cli_server_capture
    assert "easy_client_called" not in cli_server_capture


def test_http_refuses_jesus_take_the_wheel_even_on_loopback(cli_server_capture, cli_runner) -> None:
    result = _invoke(cli_runner, [*BASE, "--http", "--jesus-take-the-wheel"])

    assert result.exit_code != 0
    assert "--jesus-take-the-wheel" in result.output
    assert "server_name" not in cli_server_capture


def test_http_refuses_jesus_take_the_wheel_with_remote_opt_in(cli_server_capture, cli_runner) -> None:
    result = _invoke(
        cli_runner, [*BASE, "--http", "--host", ALL_INTERFACES, "--http-allow-remote", "--jesus-take-the-wheel"]
    )

    assert result.exit_code != 0
    assert "server_name" not in cli_server_capture


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_http_starts_on_loopback(cli_server_capture, cli_runner, host: str) -> None:
    result = _invoke(cli_runner, [*BASE, "--http", "--host", host])

    assert result.exit_code == 0
    assert cli_server_capture["anyio_args"][:2] == ("streamable-http", host)


def test_http_remote_bind_requires_explicit_opt_in(cli_server_capture, cli_runner) -> None:
    result = _invoke(cli_runner, [*BASE, "--http", "--host", ALL_INTERFACES, "--http-allow-remote"])

    assert result.exit_code == 0
    assert "Warning" in result.output
    assert cli_server_capture["anyio_args"] == ("streamable-http", ALL_INTERFACES, 8000, True)


def test_stdio_ignores_host(cli_server_capture, cli_runner) -> None:
    result = _invoke(cli_runner, [*BASE, "--host", ALL_INTERFACES])

    assert result.exit_code == 0
    assert cli_server_capture["anyio_args"][0] == "stdio"


@pytest.mark.anyio
@pytest.mark.parametrize("host", [ALL_INTERFACES, "10.0.0.5"])
async def test_server_run_refuses_remote_host_without_opt_in(host: str) -> None:
    server = SchwabMCPServer("schwab-mcp", AsyncClient.__new__(AsyncClient), approval_manager=None, allow_write=False)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="loopback"):
        await server.run(transport="http", host=host, port=1)


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:8080", "http://signal.example.com", "https://192.168.1.2:8080", "not a url"]
)
def test_signal_refuses_remote_daemon(cli_server_capture, cli_runner, url: str) -> None:
    result = _invoke(cli_runner, [*BASE, *SIGNAL, "--signal-api-url", url])

    assert result.exit_code != 0
    assert "--signal-allow-remote" in result.output
    assert "server_name" not in cli_server_capture


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://localhost:8080/", "http://[::1]:8080"])
def test_signal_accepts_loopback_daemon(cli_server_capture, cli_runner, url: str) -> None:
    result = _invoke(cli_runner, [*BASE, *SIGNAL, "--signal-api-url", url])

    assert result.exit_code == 0
    assert cli_server_capture["allow_write"] is True


def test_signal_remote_daemon_with_opt_in(cli_server_capture, cli_runner) -> None:
    result = _invoke(cli_runner, [*BASE, *SIGNAL, "--signal-api-url", "http://10.0.0.5:8080", "--signal-allow-remote"])

    assert result.exit_code == 0
    assert cli_server_capture["allow_write"] is True


def test_signal_url_not_checked_when_signal_unused(cli_server_capture, cli_runner) -> None:
    result = _invoke(cli_runner, [*BASE, "--signal-api-url", "http://10.0.0.5:8080"])

    assert result.exit_code == 0


@pytest.mark.parametrize("url", ["http://api.schwabapi.com", "http://10.0.0.5", "ftp://api.schwabapi.com", "x"])
def test_server_refuses_unencrypted_base_url(cli_server_capture, cli_runner, url: str) -> None:
    result = _invoke(cli_runner, [*BASE, "--base-url", url])

    assert result.exit_code != 0
    assert "https" in result.output
    assert "easy_client_called" not in cli_server_capture


@pytest.mark.parametrize("url", ["https://api.schwabapi.com", "https://proxy.internal:8443", "http://127.0.0.1:9000"])
def test_server_accepts_https_or_loopback_base_url(cli_server_capture, cli_runner, url: str) -> None:
    result = _invoke(cli_runner, [*BASE, "--base-url", url])

    assert result.exit_code == 0
    assert cli_server_capture["easy_client_kwargs"]["base_url"] == url


def test_auth_refuses_unencrypted_base_url(cli_auth_capture, cli_runner) -> None:
    result = cli_runner.invoke(
        cli.cli, ["auth", "--client-id", "client", "--client-secret", "secret", "--base-url", "http://example.com"]
    )

    assert result.exit_code == 1
    assert "https" in result.output
    assert "easy_client_kwargs" not in cli_auth_capture


def test_base_url_env_var_is_checked(monkeypatch, cli_server_capture, cli_runner) -> None:
    monkeypatch.setenv("SCHWAB_BASE_URL", "http://example.com")

    result = _invoke(cli_runner, BASE)

    assert result.exit_code != 0
    assert "easy_client_called" not in cli_server_capture
