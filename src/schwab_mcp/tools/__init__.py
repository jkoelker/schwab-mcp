from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.tools import account as _account
from schwab_mcp.tools import history as _history
from schwab_mcp.tools import options as _options
from schwab_mcp.tools import orders as _orders
from schwab_mcp.tools import quotes as _quotes
from schwab_mcp.tools import tools as _tools
from schwab_mcp.tools import transactions as _txns

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
        register_module = getattr(module, "register", None)
        if register_module is None:
            raise AttributeError(f"Tool module {module.__name__} missing register()")
        register_module(server, allow_write=allow_write)


__all__ = ["register_tools"]
