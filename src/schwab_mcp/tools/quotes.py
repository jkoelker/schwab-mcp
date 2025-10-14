# 

from typing import Annotated

from mcp.server.fastmcp import Context

from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call, get_quotes_client


@register
async def get_quotes(
    ctx: Context,
    symbols: Annotated[
        list[str] | str, "List of symbols or comma-separated string (e.g., ['AAPL', 'MSFT'] or 'GOOG,AMZN')"
    ],
    fields: Annotated[
        list[str] | str | None,
        "Data fields (list/str): QUOTE, FUNDAMENTAL, EXTENDED, REFERENCE, REGULAR. Default is QUOTE.",
    ] = None,
    indicative: Annotated[
        bool | None, "True for indicative quotes (extended hours/futures)"
    ] = None,
) -> str:
    """
    Returns current market quotes for specified symbols (stocks, ETFs, indices, options).
    Params: symbols (list or comma-separated string), fields (list/str: QUOTE/FUNDAMENTAL/etc.), indicative (bool).
    """
    client = get_quotes_client(ctx)

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
