from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as types
from mcp.shared.exceptions import McpError

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
    raise McpError(types.ErrorData(code=403, message="Write tools are disabled.", data=data))


__all__ = ["call", "set_write_enabled", "ensure_write_access"]
