from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.tools.registry import iter_registered_tools, register
from schwab_mcp.tools import utils as tool_utils

# Import tool modules for their registration side effects
from schwab_mcp.tools import tools as _tools  # noqa: F401
from schwab_mcp.tools import account as _account  # noqa: F401
from schwab_mcp.tools import history as _history  # noqa: F401
from schwab_mcp.tools import options as _options  # noqa: F401
from schwab_mcp.tools import orders as _orders  # noqa: F401
from schwab_mcp.tools import quotes as _quotes  # noqa: F401
from schwab_mcp.tools import transactions as _txns  # noqa: F401

def register_tools(server: FastMCP, client: AsyncClient, *, allow_write: bool) -> None:
    """Register all Schwab tools with the provided FastMCP server."""
    tool_utils.set_write_enabled(allow_write)
    setattr(server, "_schwab_client", client)

    for func in iter_registered_tools():
        if getattr(func, "_write", False) and not allow_write:
            continue
        annotations = getattr(func, "_tool_annotations", None)
        tool_kwargs = {
            "name": func.__name__,
            "description": func.__doc__,
        }
        if annotations is not None:
            tool_kwargs["annotations"] = annotations
        server.tool(**tool_kwargs)(func)


__all__ = ["register_tools", "register"]
