from __future__ import annotations

import inspect

from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.tools.registry import register

# Import tool modules for their registration side effects
from schwab_mcp.tools import tools as _tools  # noqa: F401
from schwab_mcp.tools import account as _account  # noqa: F401
from schwab_mcp.tools import history as _history  # noqa: F401
from schwab_mcp.tools import options as _options  # noqa: F401
from schwab_mcp.tools import orders as _orders  # noqa: F401
from schwab_mcp.tools import quotes as _quotes  # noqa: F401
from schwab_mcp.tools import transactions as _txns  # noqa: F401

_TOOL_MODULES = (
    _tools,
    _account,
    _history,
    _options,
    _orders,
    _quotes,
    _txns,
)


def register_tools(server: FastMCP, client: AsyncClient, *, allow_write: bool) -> None:
    """Register all Schwab tools with the provided FastMCP server."""
    _ = client

    for module in _TOOL_MODULES:
        for _, func in inspect.getmembers(module, inspect.iscoroutinefunction):
            if not getattr(func, "_registered_tool", False):
                continue
            if getattr(func, "_write", False) and not allow_write:
                continue
            annotations = getattr(func, "_tool_annotations", None)
            server.add_tool(
                func,
                name=func.__name__,
                description=func.__doc__,
                annotations=annotations,
            )


__all__ = ["register_tools", "register"]
