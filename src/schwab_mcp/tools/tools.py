#

from typing import Annotated

import datetime
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import JSONType, call


@register
async def get_datetime() -> str:
    """
    Get the current datetime in ISO format (e.g., '2023-10-27T10:30:00.123456').
    """
    return datetime.datetime.now().isoformat()


@register
async def get_market_hours(
    ctx: SchwabContext,
    markets: Annotated[
        list[str] | str,
        "Markets (list/str): EQUITY, OPTION, BOND, FUTURE, FOREX",
    ],
    date: Annotated[
        str | None,
        "Date ('YYYY-MM-DD', default today, max 1 year future)",
    ] = None,
) -> JSONType:
    """
    Get market hours for specified markets (EQUITY, OPTION, etc.) on a given date (YYYY-MM-DD, default today).
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.tools

    if isinstance(markets, str):
        markets = [m.strip() for m in markets.split(",")]

    market_enums = [client.MarketHours.Market[m.upper()] for m in markets]

    date_obj = None
    if date is not None:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()

    return await call(client.get_market_hours, market_enums, date=date_obj)


@register
async def get_movers(
    ctx: SchwabContext,
    index: Annotated[
        str,
        "Index/market: DJI, COMPX, SPX, NYSE, NASDAQ, OTCBB, INDEX_ALL, EQUITY_ALL, OPTION_ALL, OPTION_PUT, OPTION_CALL",
    ],
    sort: Annotated[
        str | None,
        "Sort criteria: VOLUME, TRADES, PERCENT_CHANGE_UP, PERCENT_CHANGE_DOWN",
    ] = None,
    frequency: Annotated[
        str | None, "Min % change threshold: ZERO, ONE, FIVE, TEN, THIRTY, SIXTY"
    ] = None,
) -> JSONType:
    """
    Get top 10 movers for an index/market (e.g., DJI, SPX, NASDAQ).
    Params: index, sort (VOLUME/TRADES/PERCENT_CHANGE_UP/DOWN), frequency (min % change: ZERO/ONE/etc.).
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.tools

    return await call(
        client.get_movers,
        client.Movers.Index[index.upper()],
        sort_order=client.Movers.SortOrder[sort.upper()] if sort else None,
        frequency=client.Movers.Frequency[frequency.upper()] if frequency else None,
    )


@register
async def get_instruments(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol or search term"],
    projection: Annotated[
        str,
        (
            "Search method/data type: SYMBOL_SEARCH (default), SYMBOL_REGEX, "
            "DESCRIPTION_SEARCH, DESCRIPTION_REGEX, SEARCH, FUNDAMENTAL"
        ),
    ] = "symbol-search",
) -> JSONType:
    """
    Search for instruments by symbol or description.
    Params: symbol (search term), projection (SYMBOL_SEARCH/SYMBOL_REGEX/etc., default symbol-search).
    Examples: get_instruments("AAPL"), get_instruments("AAPL .*", "symbol-regex"), get_instruments("AAPL", "fundamental").
    """
    # Map common variations to the correct enum names
    projection_map = {
        "symbol-search": "SYMBOL_SEARCH",
        "symbol_search": "SYMBOL_SEARCH",
        "symbol-regex": "SYMBOL_REGEX",
        "symbol_regex": "SYMBOL_REGEX",
        "description-search": "DESCRIPTION_SEARCH",
        "description_search": "DESCRIPTION_SEARCH",
        "description-regex": "DESCRIPTION_REGEX",
        "description_regex": "DESCRIPTION_REGEX",
        "search": "SEARCH",
        "fundamental": "FUNDAMENTAL",
    }
    proj_upper = projection.upper()
    proj_key = projection.lower()

    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.tools

    if proj_key in projection_map:
        proj_enum_name = projection_map[proj_key]
    elif proj_upper in client.Instrument.Projection.__members__:
        proj_enum_name = proj_upper
    else:
        raise ValueError(f"Invalid projection value: {projection}")

    return await call(
        client.get_instruments,
        symbol,
        projection=client.Instrument.Projection[proj_enum_name],
    )
