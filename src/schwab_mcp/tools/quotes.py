#

from typing import Annotated

import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_quotes(
    client: schwab.client.AsyncClient,
    symbols: Annotated[
        list[str] | str, "List of symbols to get quotes for (comma-separated if string)"
    ],
    fields: Annotated[
        list[str] | str | None,
        "Data fields to include (QUOTE, FUNDAMENTAL, EXTENDED, REFERENCE, REGULAR)",
    ] = None,
    indicative: Annotated[
        bool | None, "Include indicative quotes for extended hours or futures"
    ] = None,
) -> str:
    """
    Returns current market quotes for specified symbols.

    Retrieves real-time or delayed quote data for stocks, ETFs, indices, and options.
    Symbols can be provided as a list or comma-separated string.

    Fields options:
      QUOTE - Basic price data (bid, ask, last)
      FUNDAMENTAL - Company fundamentals (PE ratio, dividend)
      EXTENDED - Extended quote data
      REFERENCE - Reference data
      REGULAR - Regular session quotes

    Set indicative=True for extended hours or futures quotes.
    """
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]

    return await call(
        client.get_quotes,
        symbols,
        fields=[client.Quote.Fields[f] for f in fields] if fields else None,
        indicative=indicative if indicative is not None else None,
    )
