from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import mcp.types as types
from mcp.shared.exceptions import McpError
from mcp.server.fastmcp import Context
from schwab.client import AsyncClient

from schwab_mcp.tools._protocols import (
    AccountClient,
    OptionsClient,
    OrdersClient,
    PriceHistoryClient,
    QuotesClient,
    ToolsClient,
    TransactionsClient,
)

_WRITE_ENABLED: bool = False
_CLIENT_ATTR = "_schwab_client"
ClientT = TypeVar("ClientT")


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


def _missing_client_error() -> McpError:
    data = {
        "client": "unavailable",
        "hint": "Schwab client not attached to FastMCP server.",
    }
    return McpError(types.ErrorData(code=500, message="Schwab client is not configured.", data=data))


def get_client(ctx: Context) -> AsyncClient:
    """Fetch the Schwab AsyncClient stored on the FastMCP server."""
    client = getattr(ctx.fastmcp, _CLIENT_ATTR, None)
    if client is None:
        raise _missing_client_error()
    return cast(AsyncClient, client)


def get_tools_client(ctx: Context) -> ToolsClient:
    return cast(ToolsClient, get_client(ctx))


def get_account_client(ctx: Context) -> AccountClient:
    return cast(AccountClient, get_client(ctx))


def get_price_history_client(ctx: Context) -> PriceHistoryClient:
    return cast(PriceHistoryClient, get_client(ctx))


def get_options_client(ctx: Context) -> OptionsClient:
    return cast(OptionsClient, get_client(ctx))


def get_orders_client(ctx: Context) -> OrdersClient:
    return cast(OrdersClient, get_client(ctx))


def get_quotes_client(ctx: Context) -> QuotesClient:
    return cast(QuotesClient, get_client(ctx))


def get_transactions_client(ctx: Context) -> TransactionsClient:
    return cast(TransactionsClient, get_client(ctx))


__all__ = [
    "call",
    "set_write_enabled",
    "ensure_write_access",
    "get_client",
    "get_tools_client",
    "get_account_client",
    "get_price_history_client",
    "get_options_client",
    "get_orders_client",
    "get_quotes_client",
    "get_transactions_client",
]
