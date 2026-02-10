from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Callable, Optional

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.tools import register_tools
from schwab_mcp.resources import register_resources
from schwab_mcp.context import SchwabServerContext
from schwab_mcp.approvals import ApprovalManager
from schwab_mcp.db import DatabaseManager, NoOpDatabaseManager


logger = logging.getLogger(__name__)


def _client_lifespan(
    client: AsyncClient,
    approval_manager: ApprovalManager,
    db_manager: DatabaseManager,
) -> Callable[[FastMCP], AsyncContextManager[SchwabServerContext]]:
    """Create a FastMCP lifespan context that exposes the Schwab async client."""

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncGenerator[SchwabServerContext, None]:
        await approval_manager.start()
        await db_manager.start()
        context = SchwabServerContext(
            client=client, approval_manager=approval_manager, db=db_manager
        )
        try:
            yield context
        finally:
            try:
                await db_manager.stop()
            except Exception:
                logger.exception("Failed to close database connection.")
            try:
                await approval_manager.stop()
            except Exception:
                logger.exception("Failed to shut down approval manager cleanly.")
            try:
                await client.close_async_session()
            except Exception:
                logger.exception(
                    "Failed to close Schwab async client session during shutdown."
                )

    return lifespan


class SchwabMCPServer:
    """Schwab Model Context Protocol server backed by FastMCP."""

    def __init__(
        self,
        name: str,
        client: AsyncClient,
        approval_manager: ApprovalManager,
        *,
        allow_write: bool,
        enable_technical_tools: bool = True,
        use_json: bool = False,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        result_transform: Callable[[Any], Any] | None = None
        if not use_json:
            try:
                from toon import encode as toon_encode
            except ImportError as exc:  # pragma: no cover - import-time failure
                raise RuntimeError(
                    "python-toon is required for Toon output. "
                    "Re-run with --json or install the dependency."
                ) from exc

            def _toon_transform(payload: Any) -> str:
                if isinstance(payload, str):
                    return payload
                return toon_encode(payload)

            result_transform = _toon_transform

        self._server = FastMCP(
            name=name,
            lifespan=_client_lifespan(
                client, approval_manager, db_manager or NoOpDatabaseManager()
            ),
        )
        register_tools(
            self._server,
            client,
            allow_write=allow_write,
            enable_technical=enable_technical_tools,
            result_transform=result_transform,
        )
        register_resources(self._server)

    async def run(self) -> None:
        """Run the server using FastMCP's stdio transport."""
        await self._server.run_stdio_async()


def send_error_response(
    error_message: str, code: int = 401, details: Optional[dict] = None
) -> None:
    """
    Send a proper MCP error response to stdout and exit.

    This function can be used before the server is started to return
    error responses in the proper MCP format.
    """
    if details is None:
        details = {}

    error_data = types.ErrorData(code=code, message=error_message, data=details)

    response = types.JSONRPCError(
        jsonrpc="2.0",
        id="pre-initialization",
        error=error_data,
    )

    json_response = response.model_dump_json()
    sys.stdout.write(f"{json_response}\n")
    sys.stdout.flush()
    sys.exit(1)
