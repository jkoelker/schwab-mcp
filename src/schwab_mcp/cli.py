"""Click CLI commands for schwab-mcp: auth, server, save-credentials."""

import os
import sys
from collections.abc import Callable
from typing import Any

import anyio
import click
from schwab.client import AsyncClient

from schwab_mcp import auth as schwab_auth, tokens
from schwab_mcp.approvals import (
    ApprovalManager,
    DiscordApprovalManager,
    DiscordApprovalSettings,
    NoOpApprovalManager,
    SignalApprovalManager,
    SignalApprovalSettings,
)
from schwab_mcp.server import SchwabMCPServer, send_error_response

APP_NAME = "schwab-mcp"
TOKEN_MAX_AGE_SECONDS = schwab_auth.DEFAULT_MAX_TOKEN_AGE_SECONDS


def _common_options(token_path_help: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Add options shared by the authentication and server commands."""

    def apply(function: Callable[..., Any]) -> Callable[..., Any]:
        """Apply the shared options to a Click command function."""
        function = click.option(
            "--base-url",
            type=str,
            envvar="SCHWAB_BASE_URL",
            default="https://api.schwabapi.com",
            help="Schwab API base URL",
        )(function)
        function = click.option(
            "--callback-url",
            type=str,
            envvar="SCHWAB_CALLBACK_URL",
            default="https://127.0.0.1:8182",
            help="Schwab callback URL",
        )(function)
        function = click.option(
            "--client-secret",
            type=str,
            required=False,
            default=None,
            envvar="SCHWAB_CLIENT_SECRET",
            help="Schwab Client Secret",
        )(function)
        function = click.option(
            "--client-id",
            type=str,
            required=False,
            default=None,
            envvar="SCHWAB_CLIENT_ID",
            help="Schwab Client ID",
        )(function)
        return click.option(
            "--token-path",
            type=str,
            default=tokens.token_path(APP_NAME),
            help=token_path_help,
        )(function)

    return apply


@click.group()
def cli():
    """Schwab Model Context Protocol CLI."""


@cli.command("auth")
@_common_options("Path to save Schwab token file")
def auth(
    token_path: str,
    client_id: str | None,
    client_secret: str | None,
    callback_url: str,
    base_url: str,
) -> int:
    """Initialize Schwab client authentication."""
    creds = tokens.load_credentials(tokens.credentials_path(APP_NAME))
    client_id = client_id or creds.client_id
    client_secret = client_secret or creds.client_secret
    if not client_id or not client_secret:
        click.echo(
            "Error: client-id and client-secret are required. "
            "Provide via --client-id/--client-secret, env vars, "
            "or store in credentials file with 'schwab-mcp save-credentials'.",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Initializing authentication flow to create token at: {token_path}")
    token_manager = tokens.Manager(token_path)

    try:
        # This will initiate the manual authentication flow
        schwab_auth.easy_client(
            client_id=client_id,
            client_secret=client_secret,
            callback_url=callback_url,
            token_manager=token_manager,
            max_token_age=TOKEN_MAX_AGE_SECONDS,
            base_url=base_url,
        )

        # If we get here, the authentication was successful
        click.echo(f"Authentication successful! Token saved to: {token_path}")
        return 0
    except Exception as e:
        click.echo(f"Authentication failed: {str(e)}", err=True)
        return 1


def _select_write_mode(
    *,
    jesus_take_the_wheel: bool,
    discord_token: str | None,
    discord_channel_id: int | None,
    approver_values: tuple[str, ...],
    discord_timeout: int,
    signal_api_url: str,
    signal_account: str | None,
    signal_approver: tuple[str, ...],
    signal_timeout: int,
    signal_account_name: tuple[str, ...],
) -> tuple[ApprovalManager, bool] | None:
    """Choose write access and its approval manager from resolved CLI values."""
    if jesus_take_the_wheel:
        return NoOpApprovalManager(), True

    discord_requested = any((discord_token, discord_channel_id, approver_values))
    signal_requested = any((signal_account, signal_approver))
    if discord_requested and signal_requested:
        send_error_response(
            "Configure either Discord or Signal approvals, not both.",
            code=400,
            details={"discord": True, "signal": True},
        )
        return None
    if signal_requested:
        approver_numbers = SignalApprovalManager.authorized_numbers(signal_approver)
        if not signal_account or not approver_numbers:
            send_error_response(
                "Signal approval configuration is required to enable write tools.",
                code=400,
                details={
                    "missing_account": not bool(signal_account),
                    "missing_approvers": not bool(approver_numbers),
                },
            )
            return None
        manager = SignalApprovalManager(
            SignalApprovalSettings(
                api_url=signal_api_url,
                account=signal_account,
                approver_numbers=approver_numbers,
                timeout_seconds=float(signal_timeout),
                account_names=SignalApprovalManager.parse_account_names(signal_account_name),
            )
        )
        return manager, True
    if not discord_requested:
        return NoOpApprovalManager(), False

    if not discord_token or not discord_channel_id:
        send_error_response(
            "Discord approval configuration is required to enable write tools.",
            code=400,
            details={
                "missing_token": not bool(discord_token),
                "missing_channel_id": not bool(discord_channel_id),
            },
        )
        return None

    approver_ids = DiscordApprovalManager.authorized_user_ids(
        [int(value) for value in approver_values] if approver_values else None
    )
    if not approver_ids:
        send_error_response(
            "Discord approver list cannot be empty. Configure at least one reviewer.",
            code=400,
            details={"approver_source": "flags_or_env"},
        )
        return None

    settings = DiscordApprovalSettings(
        token=discord_token,
        channel_id=discord_channel_id,
        approver_ids=approver_ids,
        timeout_seconds=float(discord_timeout),
    )
    return DiscordApprovalManager(settings), True


@cli.command("server")
@_common_options("Path to Schwab token file")
@click.option(
    "--jesus-take-the-wheel",
    default=False,
    is_flag=True,
    help="Allow tools to modify the portfolios, placing trades, etc.",
)
@click.option(
    "--no-technical-tools",
    default=False,
    is_flag=True,
    help="Disable optional technical analysis tools.",
)
@click.option(
    "--discord-token",
    type=str,
    envvar="SCHWAB_MCP_DISCORD_TOKEN",
    help="Discord bot token used for approval prompts.",
)
@click.option(
    "--discord-channel-id",
    type=int,
    envvar="SCHWAB_MCP_DISCORD_CHANNEL_ID",
    help="Discord channel ID where approval requests are posted.",
)
@click.option(
    "--discord-approver",
    type=str,
    multiple=True,
    help="Discord user ID allowed to approve or deny requests. Pass multiple times for several reviewers.",
)
@click.option(
    "--discord-timeout",
    type=int,
    default=600,
    show_default=True,
    envvar="SCHWAB_MCP_DISCORD_TIMEOUT",
    help="Seconds to wait for Discord approval before timing out.",
)
@click.option(
    "--signal-api-url",
    type=str,
    default="http://127.0.0.1:8080",
    show_default=True,
    envvar="SCHWAB_MCP_SIGNAL_API_URL",
    help=(
        "Base URL of the local signal-cli REST daemon "
        "(bbernhard/signal-cli-rest-api). The daemon must run in "
        "MODE=json-rpc (or json-rpc-native); other modes cannot stream "
        "replies and would silently consume them."
    ),
)
@click.option(
    "--signal-account",
    type=str,
    envvar="SCHWAB_MCP_SIGNAL_ACCOUNT",
    help="E.164 number the signal-cli daemon is registered as.",
)
@click.option(
    "--signal-approver",
    type=str,
    multiple=True,
    help=(
        "E.164 number allowed to approve or deny. Pass multiple times for "
        "several reviewers, or set SCHWAB_MCP_SIGNAL_APPROVERS to a "
        "comma-separated list."
    ),
)
@click.option(
    "--signal-timeout",
    type=int,
    default=600,
    show_default=True,
    envvar="SCHWAB_MCP_SIGNAL_TIMEOUT",
    help="Seconds to wait for Signal approval before timing out.",
)
@click.option(
    "--signal-account-name",
    type=str,
    multiple=True,
    help=(
        "Friendly name to display in approval messages for an account, "
        "keyed by the last 4 chars of its hash. Format: 'last4=Name'. "
        "Pass multiple times, or set SCHWAB_MCP_SIGNAL_ACCOUNT_NAMES to a "
        "comma-separated value (e.g. '5805=Rollover IRA,71F7=Roth IRA')."
    ),
)
@click.option(
    "--json",
    "json_output",
    default=False,
    is_flag=True,
    help="Return JSON payloads from tools instead of Toon-encoded strings.",
)
@click.option(
    "--http",
    "use_http",
    default=False,
    is_flag=True,
    help="Use streamable-http transport (binds to --host/--port) instead of stdio.",
)
@click.option(
    "--host",
    type=str,
    default="127.0.0.1",
    envvar="MCP_HOST",
    show_default=True,
    help="Host interface to bind when using --http (use 0.0.0.0 for gateway).",
)
@click.option(
    "--port",
    type=int,
    default=8000,
    envvar="MCP_PORT",
    show_default=True,
    help="TCP port when using --http transport.",
)
def server(
    token_path: str,
    client_id: str | None,
    client_secret: str | None,
    callback_url: str,
    base_url: str,
    jesus_take_the_wheel: bool,
    discord_token: str | None,
    discord_channel_id: int | None,
    discord_approver: tuple[str, ...],
    discord_timeout: int,
    signal_api_url: str,
    signal_account: str | None,
    signal_approver: tuple[str, ...],
    signal_timeout: int,
    signal_account_name: tuple[str, ...],
    no_technical_tools: bool,
    json_output: bool,
    use_http: bool,
    host: str,
    port: int,
) -> int:
    """Run the Schwab MCP server."""
    creds = tokens.load_credentials(tokens.credentials_path(APP_NAME))
    client_id = client_id or creds.client_id
    client_secret = client_secret or creds.client_secret
    if not client_id or not client_secret:
        send_error_response(
            "client-id and client-secret are required. "
            "Provide via --client-id/--client-secret, env vars, "
            "or store in credentials file with 'schwab-mcp save-credentials'.",
            code=400,
            details={
                "missing_client_id": not bool(client_id),
                "missing_client_secret": not bool(client_secret),
            },
        )
        return 1

    # No logging to stderr when in MCP mode (we'll use proper MCP responses)
    token_manager = tokens.Manager(token_path)

    try:
        client = schwab_auth.easy_client(
            client_id=client_id,
            client_secret=client_secret,
            callback_url=callback_url,
            token_manager=token_manager,
            asyncio=True,
            interactive=False,
            enforce_enums=False,
            max_token_age=TOKEN_MAX_AGE_SECONDS,
            base_url=base_url,
        )

        if not isinstance(client, AsyncClient):
            send_error_response(
                "Async client required when starting the MCP server.",
                code=500,
                details={"client_type": type(client).__name__},
            )
            return 1
    except Exception as e:
        send_error_response(
            f"Error initializing Schwab client: {str(e)}",
            code=500,
            details={"error": str(e)},
        )
        return 1

    # Check token age
    if client.token_age() >= TOKEN_MAX_AGE_SECONDS:
        send_error_response(
            "Token is older than 5 days. Please run 'schwab-mcp auth' to re-authenticate.",
            code=401,
            details={
                "token_expired": True,
                "token_age_days": client.token_age() / 86400,
            },
        )
        return 1

    try:
        approver_values: tuple[str, ...] = discord_approver
        if not approver_values:
            env_approvers = os.getenv("SCHWAB_MCP_DISCORD_APPROVERS")
            if env_approvers:
                approver_values = tuple(value.strip() for value in env_approvers.split(",") if value.strip())

        # Signal env vars are comma-split by hand (not via Click's envvar=):
        # Click splits multiple=True env values on whitespace, which mangles
        # comma-separated lists and names containing spaces.
        signal_approver_values: tuple[str, ...] = signal_approver
        if not signal_approver_values:
            env_signal_approvers = os.getenv("SCHWAB_MCP_SIGNAL_APPROVERS")
            if env_signal_approvers:
                signal_approver_values = tuple(
                    value.strip() for value in env_signal_approvers.split(",") if value.strip()
                )

        signal_account_name_values: tuple[str, ...] = signal_account_name
        if not signal_account_name_values:
            env_signal_names = os.getenv("SCHWAB_MCP_SIGNAL_ACCOUNT_NAMES")
            if env_signal_names:
                # parse_account_names comma-splits each entry itself.
                signal_account_name_values = (env_signal_names,)

        write_mode = _select_write_mode(
            jesus_take_the_wheel=jesus_take_the_wheel,
            discord_token=discord_token,
            discord_channel_id=discord_channel_id,
            approver_values=approver_values,
            discord_timeout=discord_timeout,
            signal_api_url=signal_api_url,
            signal_account=signal_account,
            signal_approver=signal_approver_values,
            signal_timeout=signal_timeout,
            signal_account_name=signal_account_name_values,
        )
        if write_mode is None:
            return 1
        approval_manager, allow_write = write_mode

        backend_configured = any(
            (
                discord_token,
                discord_channel_id,
                approver_values,
                signal_account,
                signal_approver_values,
            )
        )
        if jesus_take_the_wheel and backend_configured:
            click.echo("Warning: --jesus-take-the-wheel bypasses configured approvals.", err=True)

        server = SchwabMCPServer(
            APP_NAME,
            client,
            approval_manager=approval_manager,
            allow_write=allow_write,
            enable_technical_tools=not no_technical_tools,
            use_json=json_output,
        )
        transport = "streamable-http" if use_http else "stdio"
        anyio.run(server.run, transport, host, port, backend="asyncio")
        return 0
    except Exception as e:
        send_error_response(f"Error running server: {str(e)}", code=500, details={"error": str(e)})
        return 1


@cli.command("save-credentials")
@click.option(
    "--client-id",
    type=str,
    prompt="Schwab Client ID",
    help="Schwab Client ID",
)
@click.option(
    "--client-secret",
    type=str,
    prompt="Schwab Client Secret",
    hide_input=True,
    help="Schwab Client Secret",
)
def save_credentials(client_id: str, client_secret: str) -> None:
    """Save Schwab client credentials to a local file."""
    path = tokens.credentials_path(APP_NAME)
    tokens.save_credentials(path, client_id, client_secret)
    click.echo(f"Credentials saved to: {path}")


def main():
    """Main entry point for the application."""
    return cli()


if __name__ == "__main__":
    sys.exit(main())
