"""Quote retrieval tools for the Schwab MCP server."""

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call

_COMPACT_QUOTE_FIELDS = (
    "lastPrice",
    "bidPrice",
    "askPrice",
    "mark",
    "netChange",
    "netPercentChange",
    "highPrice",
    "lowPrice",
    "totalVolume",
)


def _prune_quote(symbol_key: str, entry: dict[str, JSONType]) -> dict[str, JSONType]:
    result: dict[str, JSONType] = {"symbol": entry.get("symbol", symbol_key)}
    quote_sub = entry.get("quote", {})
    if isinstance(quote_sub, dict):
        for k in _COMPACT_QUOTE_FIELDS:
            if k in quote_sub:
                result[k] = quote_sub[k]
    return result


def _prune_quotes(payload: JSONType) -> JSONType:
    if not isinstance(payload, dict):
        return payload
    return {k: _prune_quote(k, v) if isinstance(v, dict) else v for k, v in payload.items()}


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
    indicative: Annotated[bool | None, "True for indicative quotes (extended hours/futures)"] = None,
    verbose: Annotated[
        bool,
        "Return the full raw payload (quote/fundamental/reference/regular blocks) instead of the compact default.",
    ] = False,
) -> JSONType:
    """Returns current market quotes for specified symbols (stocks, ETFs, indices, options).
    Params: symbols (list or comma-separated string), fields (list/str: QUOTE/FUNDAMENTAL/etc.), indicative (bool).
    By default returns compact quote fields only (lastPrice, bidPrice, askPrice, mark, netChange, netPercentChange, highPrice, lowPrice, totalVolume); pass verbose=True for the full raw payload.
    """
    client = ctx.quotes

    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]

    field_enums = None
    if fields:
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",")]
        field_enums = [client.Quote.Fields[f.upper()] for f in fields]

    result = await call(
        client.get_quotes,
        symbols,
        fields=field_enums,
        indicative=indicative if indicative is not None else None,
    )
    return result if verbose else _prune_quotes(result)


_READ_ONLY_TOOLS = (get_quotes,)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register quote tools with the MCP server."""
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
