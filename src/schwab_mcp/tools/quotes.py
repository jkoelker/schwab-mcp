#

from typing import Annotated

from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import JSONType, call


@register
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
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.quotes

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
