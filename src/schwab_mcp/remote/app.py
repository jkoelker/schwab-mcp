"""Remote MCP server application.

Combines:
- OAuth 2.1 endpoints for claude.ai authentication
- Streamable HTTP transport for MCP at /mcp
- Schwab token management via Postgres (same Cloud SQL instance)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable

from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from schwab import auth as schwab_auth
from schwab.client import AsyncClient
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from schwab_mcp.approvals import (
    ApprovalManager,
    DiscordApprovalManager,
    DiscordApprovalSettings,
    NoOpApprovalManager,
)
from schwab_mcp.db import CloudSQLManager, DatabaseManager, NoOpDatabaseManager
from schwab_mcp.resources import register_resources
from schwab_mcp.server import _client_lifespan
from schwab_mcp.tools import register_tools

from .config import RemoteServerConfig
from .oauth import SchwabMCPOAuthProvider
from .token_storage import PostgresTokenStorage

logger = logging.getLogger(__name__)


def _create_schwab_client(
    config: RemoteServerConfig,
    token_storage: PostgresTokenStorage,
) -> AsyncClient:
    """Create a schwab-py AsyncClient using Postgres-backed token storage."""
    if not token_storage.exists():
        raise RuntimeError(
            "Schwab token not found in database. "
            "Visit the admin service to authenticate with Schwab first."
        )

    client = schwab_auth.client_from_access_functions(
        config.schwab_client_id,
        config.schwab_client_secret,
        token_storage.load,
        token_storage.write,
        asyncio=True,
        enforce_enums=False,
        base_url=config.schwab_base_url,
    )

    if not isinstance(client, AsyncClient):
        raise RuntimeError("Expected AsyncClient from schwab-py")

    return client


def _create_approval_manager(
    config: RemoteServerConfig,
) -> tuple[ApprovalManager, bool]:
    """Create the approval manager based on config. Returns (manager, allow_write)."""
    if config.jesus_take_the_wheel:
        logger.warning(
            "JESUS_TAKE_THE_WHEEL is active. "
            "ALL write tool invocations will be auto-approved WITHOUT human review."
        )
        return NoOpApprovalManager(), True

    if config.discord_token and config.discord_channel_id:
        approver_ids_raw = [
            int(x.strip()) for x in config.discord_approvers.split(",") if x.strip()
        ]
        approver_ids = DiscordApprovalManager.authorized_user_ids(
            approver_ids_raw or None
        )
        if not approver_ids:
            logger.warning(
                "Discord configured but no approvers specified. "
                "Write tools will be disabled."
            )
            return NoOpApprovalManager(), False

        settings = DiscordApprovalSettings(
            token=config.discord_token,
            channel_id=config.discord_channel_id,
            approver_ids=approver_ids,
            timeout_seconds=float(config.discord_timeout),
        )
        return DiscordApprovalManager(settings), True

    return NoOpApprovalManager(), False


def create_mcp_server(
    config: RemoteServerConfig,
    schwab_client: AsyncClient,
    approval_manager: ApprovalManager,
    allow_write: bool,
    db_manager: DatabaseManager | None = None,
) -> FastMCP:
    """Create the FastMCP server with all tools registered."""
    result_transform: Callable[[Any], Any] | None = None
    if not config.json_output:
        try:
            from toon import encode as toon_encode
        except ImportError as exc:
            raise RuntimeError(
                "python-toon required for Toon output. Set JSON_OUTPUT=true or install."
            ) from exc

        def _toon_transform(payload: Any) -> str:
            if isinstance(payload, str):
                return payload
            return toon_encode(payload)

        result_transform = _toon_transform

    mcp = FastMCP(
        "schwab-mcp",
        stateless_http=True,
        json_response=True,
        lifespan=_client_lifespan(
            schwab_client,
            approval_manager,
            db_manager or NoOpDatabaseManager(),
        ),
    )
    register_tools(
        mcp,
        schwab_client,
        allow_write=allow_write,
        enable_technical=not config.no_technical_tools,
        result_transform=result_transform,
    )
    register_resources(mcp)
    return mcp


def create_app(config: RemoteServerConfig) -> Starlette:
    """Build the full Starlette application with OAuth + MCP endpoints."""

    # Validate config
    errors = config.validate()
    if errors:
        raise ValueError(f"Invalid configuration: {'; '.join(errors)}")

    # OAuth provider for claude.ai auth
    oauth_provider = SchwabMCPOAuthProvider(
        server_url=config.server_url,
        mcp_oauth_secret=config.mcp_oauth_client_secret,
    )

    # OAuth auth settings
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(config.server_url),
        resource_server_url=AnyHttpUrl(config.server_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
        required_scopes=["mcp"],
    )

    # OAuth routes from the MCP SDK
    oauth_routes = create_auth_routes(
        provider=oauth_provider,
        issuer_url=auth_settings.issuer_url,
        service_documentation_url=auth_settings.service_documentation_url,
        client_registration_options=auth_settings.client_registration_options,
        revocation_options=auth_settings.revocation_options,
    )

    # Consent page routes (custom, not part of SDK)
    async def consent_page(request: Request) -> Response:
        state = request.query_params.get("state")
        if not state:
            raise HTTPException(status_code=400, detail="Missing state parameter")
        return await oauth_provider.get_consent_page(state)

    async def consent_approve(request: Request) -> Response:
        return await oauth_provider.handle_consent(request)

    # Health check
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "schwab-mcp"})

    # Combine all routes
    all_routes = list(oauth_routes) + [
        Route("/consent", endpoint=consent_page, methods=["GET"]),
        Route("/consent/approve", endpoint=consent_approve, methods=["POST"]),
        Route("/health", endpoint=health, methods=["GET"]),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        """Initialize DB, Schwab client, and MCP server on startup."""
        # Connect to the existing Cloud SQL Postgres database
        db_manager = CloudSQLManager(config.database_config)
        await db_manager.start()
        logger.info("Database connected")

        # Create token storage using the same DB connection
        token_storage = PostgresTokenStorage(db=db_manager)
        await token_storage.ensure_table()
        app.state.token_storage = token_storage

        # Load the Schwab token from Postgres
        schwab_client: AsyncClient | None = None
        try:
            await token_storage.load_async()
            schwab_client = _create_schwab_client(config, token_storage)
            logger.info("Schwab client initialized from Postgres token")
        except Exception:
            logger.exception(
                "Failed to initialize Schwab client. "
                "Tools will fail until a valid token is in the database."
            )

        approval_manager, allow_write = _create_approval_manager(config)
        mcp_server = create_mcp_server(
            config,
            schwab_client or _create_dummy_client(),
            approval_manager,
            allow_write,
            db_manager=db_manager,
        )

        # Mount the MCP streamable HTTP app
        mcp_app = mcp_server.streamable_http_app()
        app.routes.append(Mount("/mcp", app=mcp_app))

        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                await db_manager.stop()

    app = Starlette(routes=all_routes, lifespan=lifespan)
    return app


def _create_dummy_client() -> AsyncClient:
    """Create a placeholder client that will fail on use.

    This allows the server to start and serve OAuth endpoints even when
    the Schwab token is not yet available.
    """

    class _DummyClient:
        """Raises an error on any attribute access."""

        def __getattr__(self, name: str) -> Any:
            raise RuntimeError(
                "Schwab client is not initialized. "
                "The Schwab token may be missing or expired. "
                "Visit the admin service to re-authenticate."
            )

    return _DummyClient()  # type: ignore[return-value]
