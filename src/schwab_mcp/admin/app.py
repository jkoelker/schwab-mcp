"""Admin service for Schwab OAuth re-authentication.

This is a lightweight web app that handles the Schwab browser-based OAuth
flow and writes the resulting token to the shared Postgres database. It is
the only service that initiates Schwab OAuth — the MCP server only reads tokens.

You visit this service in your browser roughly every 7 days when the
Schwab refresh token expires.

Connects to the same Cloud SQL Postgres instance as the MCP server.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import secrets
from collections.abc import AsyncGenerator
from typing import Any

from schwab import auth as schwab_auth
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from schwab_mcp.db import CloudSQLManager
from schwab_mcp.remote.config import AdminConfig
from schwab_mcp.remote.token_storage import PostgresTokenStorage

logger = logging.getLogger(__name__)


def create_admin_app(config: AdminConfig) -> Starlette:
    """Create the admin Starlette application."""
    errors = config.validate()
    if errors:
        raise ValueError(f"Invalid admin configuration: {'; '.join(errors)}")

    # PKCE / state storage for the Schwab OAuth flow
    _oauth_state: dict[str, Any] = {}

    async def index(request: Request) -> Response:
        """Admin dashboard."""
        token_storage: PostgresTokenStorage = request.app.state.token_storage
        token_info = await _get_token_info(token_storage)
        status_class = "ok" if token_info.get("refresh_likely_valid") else "warn"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Schwab MCP Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px; margin: 40px auto; padding: 20px;
            background: #f5f5f5;
        }}
        .card {{
            background: white; border-radius: 12px; padding: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 16px;
        }}
        h1 {{ font-size: 1.4em; margin-top: 0; }}
        .status-ok {{ color: #059669; }}
        .status-warn {{ color: #d97706; }}
        .status-error {{ color: #dc2626; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td {{ padding: 8px 0; border-bottom: 1px solid #f3f4f6; }}
        td:first-child {{ font-weight: 500; color: #6b7280; }}
        a.btn {{
            display: inline-block; padding: 12px 24px; background: #2563eb;
            color: white; border-radius: 8px; text-decoration: none;
            font-weight: 500;
        }}
        a.btn:hover {{ background: #1d4ed8; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Schwab MCP Admin</h1>
        <table>
            <tr>
                <td>Token Status</td>
                <td class="status-{status_class}">
                    {"Valid" if token_info.get("exists") else "Missing"}
                </td>
            </tr>
            <tr>
                <td>Token Age</td>
                <td>{token_info.get("age_days", "N/A")} days</td>
            </tr>
            <tr>
                <td>Refresh Valid</td>
                <td class="status-{status_class}">
                    {"Likely Yes" if token_info.get("refresh_likely_valid") else "Likely Expired"}
                </td>
            </tr>
            <tr>
                <td>Created</td>
                <td>{token_info.get("created_at", "N/A")}</td>
            </tr>
        </table>
    </div>
    <div class="card">
        <h1>Re-authenticate with Schwab</h1>
        <p>Click below to initiate a new Schwab OAuth flow. This is required
        roughly every 7 days when the refresh token expires.</p>
        <a href="/schwab/auth" class="btn">Start Schwab Auth</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html)

    async def schwab_auth_start(request: Request) -> Response:
        """Initiate the Schwab OAuth flow."""
        auth_context = schwab_auth.get_auth_context(
            config.schwab_client_id,
            config.schwab_callback_url,
        )

        state = secrets.token_hex(16)
        _oauth_state[state] = {
            "auth_context": auth_context,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        auth_url = auth_context.authorization_url
        separator = "&" if "?" in auth_url else "?"
        auth_url_with_state = f"{auth_url}{separator}state={state}"

        return RedirectResponse(url=auth_url_with_state, status_code=302)

    async def schwab_callback(request: Request) -> Response:
        """Handle the Schwab OAuth callback."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        token_storage: PostgresTokenStorage = request.app.state.token_storage

        if not code:
            return HTMLResponse(
                "<h1>Error</h1><p>No authorization code received from Schwab.</p>",
                status_code=400,
            )

        received_url = str(request.url)

        auth_context = None
        if state and state in _oauth_state:
            auth_context = _oauth_state.pop(state)["auth_context"]
        elif _oauth_state:
            latest_key = max(_oauth_state.keys())
            auth_context = _oauth_state.pop(latest_key)["auth_context"]

        if auth_context is None:
            return HTMLResponse(
                "<h1>Error</h1><p>OAuth state expired. Please try again.</p>",
                status_code=400,
            )

        try:
            # Exchange code for token using a sync token writer that
            # updates the cache. We'll persist to DB right after.
            received_token: dict[str, Any] = {}

            def _capture_token(token: dict[str, Any], *a: Any, **kw: Any) -> None:
                received_token.update(token)

            client = schwab_auth.client_from_received_url(
                config.schwab_client_id,
                config.schwab_client_secret,
                auth_context,
                received_url,
                _capture_token,
                asyncio=False,
                enforce_enums=False,
            )

            # Also try to get the token from the client session
            if not received_token:
                session = getattr(client, "_session", None)
                if session is not None and hasattr(session, "token"):
                    received_token.update(session.token)

            if not received_token:
                raise RuntimeError("No token received from Schwab OAuth exchange")

            # Write to Postgres
            await token_storage.write_async(received_token)
            logger.info("Schwab token refreshed and written to Postgres")

            return HTMLResponse(
                """<!DOCTYPE html>
<html>
<head><title>Success</title>
<style>
    body { font-family: sans-serif; max-width: 500px; margin: 60px auto; padding: 20px; text-align: center; }
    .success { color: #059669; font-size: 1.5em; }
</style>
</head>
<body>
    <p class="success">Schwab authentication successful!</p>
    <p>The token has been saved to the database. The MCP server will pick it up automatically.</p>
    <p><a href="/">Back to Admin</a></p>
</body>
</html>"""
            )
        except Exception as e:
            logger.exception("Schwab OAuth callback failed")
            return HTMLResponse(
                f"""<!DOCTYPE html>
<html>
<head><title>Error</title>
<style>
    body {{ font-family: sans-serif; max-width: 500px; margin: 60px auto; padding: 20px; }}
    .error {{ color: #dc2626; }}
</style>
</head>
<body>
    <h1 class="error">Authentication Failed</h1>
    <p>{str(e)}</p>
    <p><a href="/">Back to Admin</a></p>
</body>
</html>""",
                status_code=500,
            )

    async def status_endpoint(request: Request) -> Response:
        """Health check / status endpoint."""
        token_storage: PostgresTokenStorage = request.app.state.token_storage
        info = await _get_token_info(token_storage)
        info["service"] = "schwab-mcp-admin"
        info["status"] = "ok"
        return JSONResponse(info)

    routes = [
        Route("/", endpoint=index, methods=["GET"]),
        Route("/schwab/auth", endpoint=schwab_auth_start, methods=["GET"]),
        Route("/datareceived", endpoint=schwab_callback, methods=["GET"]),
        Route("/status", endpoint=status_endpoint, methods=["GET"]),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        """Connect to the shared Postgres database on startup."""
        db_manager = CloudSQLManager(config.database_config)
        await db_manager.start()
        logger.info("Admin service connected to database")

        token_storage = PostgresTokenStorage(db=db_manager)
        await token_storage.ensure_table()
        app.state.token_storage = token_storage

        try:
            yield
        finally:
            await db_manager.stop()

    app = Starlette(routes=routes, lifespan=lifespan)
    return app


async def _get_token_info(token_storage: PostgresTokenStorage) -> dict[str, Any]:
    """Get summary information about the current Schwab token."""
    try:
        token = await token_storage.load_async()
        info: dict[str, Any] = {
            "exists": True,
            "has_access_token": "access_token" in token,
            "has_refresh_token": "refresh_token" in token,
        }
        if "creation_timestamp" in token:
            created = datetime.datetime.fromtimestamp(
                token["creation_timestamp"], tz=datetime.timezone.utc
            )
            info["created_at"] = created.isoformat()
            age_days = (
                datetime.datetime.now(datetime.timezone.utc) - created
            ).total_seconds() / 86400
            info["age_days"] = round(age_days, 2)
            info["refresh_likely_valid"] = age_days < 7
        else:
            info["refresh_likely_valid"] = None
        return info
    except FileNotFoundError:
        return {"exists": False, "refresh_likely_valid": False}
    except Exception as e:
        return {"exists": None, "error": str(e), "refresh_likely_valid": False}
