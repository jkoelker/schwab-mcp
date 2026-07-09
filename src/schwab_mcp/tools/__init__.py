"""Tool registration aggregator for all Schwab MCP tool modules."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.tools import (
    account as _account,
    history as _history,
    options as _options,
    orders as _orders,
    quotes as _quotes,
    technical as _technical,
    tools as _tools,
    transactions as _txns,
)

logger = logging.getLogger(__name__)

_TOOL_MODULES = (
    _tools,
    _account,
    _history,
    _options,
    _orders,
    _quotes,
    _txns,
)


def register_tools(
    server: FastMCP,
    client: AsyncClient,
    *,
    allow_write: bool,
    enable_technical: bool = True,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register all Schwab tools with the provided FastMCP server."""
    _ = client

    modules = _TOOL_MODULES
    if enable_technical:
        modules = modules + (_technical,)

    for module in modules:
        register_module = getattr(module, "register", None)
        if register_module is None:
            raise AttributeError(f"Tool module {module.__name__} missing register()")
        register_module(
            server,
            allow_write=allow_write,
            result_transform=result_transform,
        )


__all__ = ["register_tools"]
