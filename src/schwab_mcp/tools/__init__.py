from __future__ import annotations

import functools
import inspect
from typing import Any, Awaitable, Callable, cast

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

ToolCallable = Callable[..., Awaitable[Any]]


def _bind_tool(func: ToolCallable, client: AsyncClient) -> ToolCallable:
    """Partially bind the Schwab client to the tool callable."""
    @functools.wraps(func)
    async def bound(*args: Any, **kwargs: Any) -> Any:
        return await func(client, *args, **kwargs)

    sig = inspect.signature(func)
    parameters = list(sig.parameters.values())
    if parameters and parameters[0].name == "client":
        parameters = parameters[1:]
    cast(Any, bound).__signature__ = sig.replace(parameters=parameters)

    annotations = dict(getattr(func, "__annotations__", {}))
    annotations.pop("client", None)
    bound.__annotations__ = annotations

    return bound


def register_tools(server: FastMCP, client: AsyncClient, *, allow_write: bool) -> None:
    """Register all Schwab tools with the provided FastMCP server."""
    tool_utils.set_write_enabled(allow_write)

    for func in iter_registered_tools():
        if getattr(func, "_write", False) and not allow_write:
            continue
        bound = _bind_tool(func, client)
        server.add_tool(bound, name=func.__name__, description=func.__doc__)


__all__ = ["register_tools", "register"]
