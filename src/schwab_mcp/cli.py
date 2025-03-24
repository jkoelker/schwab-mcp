import click
import sys
import anyio

from schwab_mcp.server import SchwabMCPServer, send_error_response
from schwab_mcp import auth as schwab_auth
from schwab_mcp import tokens


APP_NAME = "schwab-mcp"


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
def server(
    token_path: str,
    client_id: str,
    client_secret: str,
    callback_url: str,
    jesus_take_the_wheel: bool,
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
        )
    except Exception as e:
        send_error_response(
            f"Error initializing Schwab client: {str(e)}",
            code=500,
            details={"error": str(e)},
        )
        return 1

    # Check token age
    if client.token_age() > 5 * 86400:
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
        server = SchwabMCPServer(APP_NAME, client, jesus_take_the_wheel=jesus_take_the_wheel)
        anyio.run(server.run)
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
