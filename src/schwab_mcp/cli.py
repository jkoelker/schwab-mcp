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
from schwab_mcp.db import CloudSQLManager, DatabaseConfig, NoOpDatabaseManager


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
@click.option(
    "--base-url",
    type=str,
    envvar="SCHWAB_BASE_URL",
    default="https://api.schwabapi.com",
    help="Schwab API base URL",
)
@click.option(
    "--browser",
    type=str,
    default=None,
    help="Browser to use for authentication (e.g., 'safari', 'firefox'). Chrome often blocks self-signed certs.",
)
@click.option(
    "--manual",
    is_flag=True,
    default=False,
    help="Use manual flow - you'll paste the callback URL instead of using a local server.",
)
def auth(
    token_path: str,
    client_id: str,
    client_secret: str,
    callback_url: str,
    base_url: str,
    browser: str | None,
    manual: bool,
) -> int:
    """Initialize Schwab client authentication."""
    click.echo("=" * 80)
    click.echo("SCHWAB MCP AUTHENTICATION")
    click.echo("=" * 80)
    click.echo()
    click.echo(f"Token will be saved to: {token_path}")
    click.echo()
    click.echo("Configuration:")
    click.echo(f"  Client ID: {client_id[:20]}...")
    click.echo(f"  Callback URL: {callback_url}")
    click.echo(f"  Base URL: {base_url}")
    click.echo()
    click.echo(
        "IMPORTANT: Verify these match EXACTLY with your Schwab Developer Portal:"
    )
    click.echo("  1. Go to: https://developer.schwab.com/dashboard")
    click.echo("  2. Click on your app")
    click.echo("  3. Compare the 'App Key' and 'Callback URL' values")
    click.echo()
    click.echo("=" * 80)
    click.echo()

    token_manager = tokens.Manager(token_path)

    try:
        if manual:
            # Use manual flow - user pastes the callback URL
            from schwab import auth as schwab_raw_auth

            client = schwab_raw_auth.client_from_manual_flow(
                api_key=client_id,
                app_secret=client_secret,
                callback_url=callback_url,
                token_path=token_path,
                asyncio=False,
                base_url=base_url,
            )

            # Save token using our manager
            if hasattr(client, "_session") and hasattr(client._session, "token"):
                token_manager.write(client._session.token)
        else:
            # This will initiate the automatic authentication flow
            schwab_auth.easy_client(
                client_id=client_id,
                client_secret=client_secret,
                callback_url=callback_url,
                token_manager=token_manager,
                max_token_age=TOKEN_MAX_AGE_SECONDS,
                base_url=base_url,
                requested_browser=browser,
            )

        # If we get here, the authentication was successful
        click.echo()
        click.echo("=" * 80)
        click.echo("✓ Authentication successful!")
        click.echo("=" * 80)
        click.echo(f"Token saved to: {token_path}")
        return 0
    except Exception as e:
        click.echo()
        click.echo("=" * 80)
        click.echo("✗ Authentication failed")
        click.echo("=" * 80)
        click.echo(f"Error: {str(e)}", err=True)
        click.echo()
        click.echo("Common issues:")
        click.echo("  1. Client ID or Secret doesn't match Developer Portal")
        click.echo("  2. Callback URL doesn't match Developer Portal")
        click.echo("  3. Callback URL was changed recently (wait until market close)")
        click.echo("  4. Browser blocked the popup or redirect")
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
    "--base-url",
    type=str,
    envvar="SCHWAB_BASE_URL",
    default="https://api.schwabapi.com",
    help="Schwab API base URL",
)
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
    "--json",
    "json_output",
    default=False,
    is_flag=True,
    help="Return JSON payloads from tools instead of Toon-encoded strings.",
)
@click.option(
    "--db-instance",
    type=str,
    envvar="SCHWAB_DB_INSTANCE",
    help="Cloud SQL instance connection name (e.g., 'project:region:instance'). Enables data storage.",
)
@click.option(
    "--db-name",
    type=str,
    envvar="SCHWAB_DB_NAME",
    default="schwab_data",
    show_default=True,
    help="Database name on the Cloud SQL instance.",
)
@click.option(
    "--db-user",
    type=str,
    envvar="SCHWAB_DB_USER",
    default="agent_user",
    show_default=True,
    help="Database user for Cloud SQL connection.",
)
@click.option(
    "--db-password",
    type=str,
    envvar="SCHWAB_DB_PASSWORD",
    help="Database password for Cloud SQL connection.",
)
def server(
    token_path: str,
    client_id: str,
    client_secret: str,
    callback_url: str,
    base_url: str,
    jesus_take_the_wheel: bool,
    discord_token: str | None,
    discord_channel_id: int | None,
    discord_approver: tuple[str, ...],
    discord_timeout: int,
    no_technical_tools: bool,
    json_output: bool,
    db_instance: str | None,
    db_name: str,
    db_user: str,
    db_password: str | None,
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

        if db_instance and db_password:
            db_manager = CloudSQLManager(
                DatabaseConfig(
                    instance_connection_name=db_instance,
                    database=db_name,
                    user=db_user,
                    password=db_password,
                )
            )
        else:
            db_manager = NoOpDatabaseManager()

        server = SchwabMCPServer(
            APP_NAME,
            client,
            approval_manager=approval_manager,
            allow_write=allow_write,
            enable_technical_tools=not no_technical_tools,
            use_json=json_output,
            db_manager=db_manager,
        )
        anyio.run(server.run, backend="asyncio")
        return 0
    except Exception as e:
        send_error_response(
            f"Error running server: {str(e)}", code=500, details={"error": str(e)}
        )
        return 1


@cli.command("init-db")
@click.option(
    "--db-instance",
    type=str,
    required=True,
    envvar="SCHWAB_DB_INSTANCE",
    help="Cloud SQL instance connection name (e.g., 'project:region:instance').",
)
@click.option(
    "--db-name",
    type=str,
    envvar="SCHWAB_DB_NAME",
    default="schwab_data",
    show_default=True,
    help="Database name on the Cloud SQL instance.",
)
@click.option(
    "--db-user",
    type=str,
    envvar="SCHWAB_DB_USER",
    default="agent_user",
    show_default=True,
    help="Database user for Cloud SQL connection.",
)
@click.option(
    "--db-password",
    type=str,
    required=True,
    envvar="SCHWAB_DB_PASSWORD",
    help="Database password for Cloud SQL connection.",
)
def init_db(
    db_instance: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> int:
    """Initialize the schwab_data database schema."""
    click.echo(f"Connecting to {db_instance}/{db_name} as {db_user}...")

    db_manager = CloudSQLManager(
        DatabaseConfig(
            instance_connection_name=db_instance,
            database=db_name,
            user=db_user,
            password=db_password,
        )
    )

    try:
        anyio.run(db_manager.start, backend="asyncio")
        click.echo("Schema initialized successfully.")
        anyio.run(db_manager.stop, backend="asyncio")
        return 0
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def main():
    """Main entry point for the application."""
    return cli()


if __name__ == "__main__":
    sys.exit(main())
