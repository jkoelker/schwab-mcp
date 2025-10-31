#
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call


async def get_quotes(
    ctx: SchwabContext,
    symbols: Annotated[
        list[str] | str,
        "List of symbols or comma-separated string (e.g., ['AAPL', 'MSFT'] or 'GOOG,AMZN')",
    ],
    fields: Annotated[
        list[str] | str | None,
        "Data fields (list/str): QUOTE, FUNDAMENTAL, EXTENDED, REFERENCE, REGULAR. Default is QUOTE.",
    ] = None,
    indicative: Annotated[
        bool | None, "True for indicative quotes (extended hours/futures)"
    ] = None,
) -> JSONType:
    """
    Returns current market quotes for specified symbols (stocks, ETFs, indices, options).
    Params: symbols (list or comma-separated string), fields (list/str: QUOTE/FUNDAMENTAL/etc.), indicative (bool).
    """
    client = ctx.quotes

    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]

    field_enums = None
    if fields:
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",")]
        field_enums = [client.Quote.Fields[f.upper()] for f in fields]

    return await call(
        client.get_quotes,
        symbols,
        fields=field_enums,
        indicative=indicative if indicative is not None else None,
    )


_READ_ONLY_TOOLS = (get_quotes,)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
