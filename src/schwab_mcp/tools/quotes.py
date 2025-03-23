#

from typing import Annotated

import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_quotes(
    client: schwab.client.AsyncClient,
    symbols: Annotated[list[str] | str, "List of stock symbols to get quotes for"],
    fields: Annotated[
        list[str] | str | None, "Fields to include in the response"
    ] = None,
    indicative: Annotated[bool | None, "Include indicative quotes"] = None,
) -> str:
    """
    Get quotes for specified symbols

    Fields can be one of the following:
        QUOTE
        FUNDAMENTAL
        EXTENDED
        REFERENCE
        REGULAR

    If fields is not provided, all fields will be returned.

    If indicative is True, symbols will be returned with their corresponding indicative quote.
    """
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]

    return await call(
        client.get_quotes,
        symbols,
        fields=[client.Quote.Fields[f] for f in fields] if fields else None,
        indicative=indicative if indicative is not None else None,
    )
