from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as types
from mcp.shared.exceptions import McpError
from mcp.server.fastmcp import Context

from schwab_mcp.context import SchwabServerContext

_WRITE_ENABLED: bool = False


async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
    """Call a method on the Schwab client and return the response text."""
    response = await func(*args, **kwargs)
    response.raise_for_status()
    return response.text


def set_write_enabled(value: bool) -> None:
    """Configure whether write tools are permitted."""
    global _WRITE_ENABLED
    _WRITE_ENABLED = value


def ensure_write_access() -> None:
    """Raise an MCP error when a write tool is invoked without permission."""
    if _WRITE_ENABLED:
        return

    data = {
        "write_enabled": False,
        "hint": "Restart the server with --jesus-take-the-wheel to enable write tools.",
    }
    raise McpError(
        types.ErrorData(code=403, message="Write tools are disabled.", data=data)
    )


def _missing_client_error() -> McpError:
    data = {
        "client": "unavailable",
        "hint": "Schwab client not attached to FastMCP lifespan context.",
    }
    return McpError(
        types.ErrorData(code=500, message="Schwab client is not configured.", data=data)
    )


def get_context(ctx: Context) -> SchwabServerContext:
    """Retrieve the shared Schwab context from the request lifespan."""

    request_context = getattr(ctx, "request_context", None)
    if request_context is None:
        raise _missing_client_error()

    lifespan_context = getattr(request_context, "lifespan_context", None)
    if not isinstance(lifespan_context, SchwabServerContext):
        raise _missing_client_error()

    return lifespan_context


__all__ = [
    "call",
    "set_write_enabled",
    "ensure_write_access",
    "get_context",
]
