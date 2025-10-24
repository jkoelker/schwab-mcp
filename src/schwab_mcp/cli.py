import click
import sys
import anyio
import os
from schwab.client import AsyncClient

from schwab_mcp.server import SchwabMCPServer, send_error_response
from schwab_mcp import auth as schwab_auth
from schwab_mcp import tokens
from schwab_mcp.approvals import (
    DiscordApprovalManager,
    DiscordApprovalSettings,
    NoOpApprovalManager,
)


APP_NAME = "schwab-mcp"
TOKEN_MAX_AGE_SECONDS = schwab_auth.DEFAULT_MAX_TOKEN_AGE_SECONDS


@click.group()
def cli():
    """Schwab Model Context Protocol CLI."""
    pass


@cli.command("auth")
@click.option(
    "--token-path",
    type=str,
    default=tokens.token_path(APP_NAME),
    help="Path to save Schwab token file",
)
@click.option(
    "--client-id",
    type=str,
    required=True,
    envvar="SCHWAB_CLIENT_ID",
    help="Schwab Client ID",
)
@click.option(
    "--client-secret",
    type=str,
    required=True,
    envvar="SCHWAB_CLIENT_SECRET",
    help="Schwab Client Secret",
)
@click.option(
    "--callback-url",
    type=str,
    envvar="SCHWAB_CALLBACK_URL",
    default="https://127.0.0.1:8182",
    help="Schwab callback URL",
)
def auth(
    token_path: str,
    client_id: str,
    client_secret: str,
    callback_url: str,
) -> int:
    """Initialize Schwab client authentication."""
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
        )

        # If we get here, the authentication was successful
        click.echo(f"Authentication successful! Token saved to: {token_path}")
        return 0
    except Exception as e:
        click.echo(f"Authentication failed: {str(e)}", err=True)
        return 1


@cli.command("server")
@click.option(
    "--token-path",
    type=str,
    default=tokens.token_path(APP_NAME),
    help="Path to Schwab token file",
)
@click.option(
    "--client-id",
    type=str,
    required=True,
    envvar="SCHWAB_CLIENT_ID",
    help="Schwab Client ID",
)
@click.option(
    "--client-secret",
    type=str,
    required=True,
    envvar="SCHWAB_CLIENT_SECRET",
    help="Schwab Client Secret",
)
@click.option(
    "--callback-url",
    type=str,
    envvar="SCHWAB_CALLBACK_URL",
    default="https://127.0.0.1:8182",
    help="Schwab callback URL",
)
@click.option(
    "--jesus-take-the-wheel",
    default=False,
    is_flag=True,
    help="Allow tools to modify the portfolios, placing trades, etc.",
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
def server(
    token_path: str,
    client_id: str,
    client_secret: str,
    callback_url: str,
    jesus_take_the_wheel: bool,
    discord_token: str | None,
    discord_channel_id: int | None,
    discord_approver: tuple[str, ...],
    discord_timeout: int,
) -> int:
    """Run the Schwab MCP server."""
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
                approver_values = tuple(
                    value.strip() for value in env_approvers.split(",") if value.strip()
                )

        discord_requested = any(
            (
                discord_token,
                discord_channel_id,
                approver_values,
            )
        )
        allow_write = False

        if jesus_take_the_wheel:
            approval_manager = NoOpApprovalManager()
            allow_write = True
        elif discord_requested:
            if not discord_token or not discord_channel_id:
                send_error_response(
                    "Discord approval configuration is required to enable write tools.",
                    code=400,
                    details={
                        "missing_token": not bool(discord_token),
                        "missing_channel_id": not bool(discord_channel_id),
                    },
                )
                return 1

            approver_ids = DiscordApprovalManager.authorized_user_ids(
                [int(value) for value in approver_values] if approver_values else None
            )
            if not approver_ids:
                send_error_response(
                    "Discord approver list cannot be empty. Configure at least one reviewer.",
                    code=400,
                    details={"approver_source": "flags_or_env"},
                )
                return 1
            settings = DiscordApprovalSettings(
                token=discord_token,
                channel_id=discord_channel_id,
                approver_ids=approver_ids,
                timeout_seconds=float(discord_timeout),
            )
            approval_manager = DiscordApprovalManager(settings)
            allow_write = True
        else:
            approval_manager = NoOpApprovalManager()

        if jesus_take_the_wheel and discord_token:
            click.echo(
                "Warning: --jesus-take-the-wheel bypasses Discord approvals.", err=True
            )

        server = SchwabMCPServer(
            APP_NAME,
            client,
            approval_manager=approval_manager,
            allow_write=allow_write,
        )
        anyio.run(server.run, backend="asyncio")
        return 0
    except Exception as e:
        send_error_response(
            f"Error running server: {str(e)}", code=500, details={"error": str(e)}
        )
        return 1


def main():
    """Main entry point for the application."""
    return cli()


if __name__ == "__main__":
    sys.exit(main())
