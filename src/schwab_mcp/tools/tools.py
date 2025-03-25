#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_datetime() -> str:
    """
    Get the current datetime in ISO format
    """
    return datetime.datetime.now().isoformat()


@register
async def get_market_hours(
    client: schwab.client.AsyncClient,
    markets: Annotated[
        list[str] | str,
        "Markets to get hours for (EQUITY, OPTION, BOND, FUTURE, FOREX)",
    ],
    date: Annotated[
        str | None,
        "Date to get hours for in 'YYYY-MM-DD' format. Accepts values up to one year from today.",
    ] = None,
) -> str:
    """
    Get market hours for a specific market.

    Market can be one of the following:
      EQUITY
      OPTION
      BOND
      FUTURE
      FOREX

    If date is not provided, the current date will be used.
    """
    if isinstance(markets, str):
        markets = [markets]

    markets = [client.MarketHours.Market[m] for m in markets]

    return await call(client.get_market_hours, markets, date=date)


@register
async def get_movers(
    client: schwab.client.AsyncClient,
    index: Annotated[
        str,
        "Index or market segment to get top movers for (DJI, COMPX, SPX, NYSE, etc.)",
    ],
    sort: Annotated[
        str,
        "Sort criteria for ranking movers (VOLUME, TRADES, PERCENT_CHANGE_UP, PERCENT_CHANGE_DOWN)",
    ] = None,
    frequency: Annotated[
        str, "Minimum percentage change threshold (ZERO, ONE, FIVE, TEN, THIRTY, SIXTY)"
    ] = None,
) -> str:
    """
    Get a list of the top ten movers for a specific index.

    Index can be one of the following:
      DJI
      COMPX
      SPX
      NYSE
      NASDAQ
      OTCBB
      INDEX_ALL
      EQUITY_ALL
      OPTION_ALL
      OPTION_PUT
      OPTION_CALL

    Sort can be one of the following:
      VOLUME
      TRADES
      PERCENT_CHANGE_UP
      PERCENT_CHANGE_DOWN

    Frequency can be one of the following:
      ZERO
      ONE
      FIVE
      TEN
      THIRTY
      SIXTY
    """
    return await call(
        client.get_movers,
        index=client.Movers.Index[index],
        sort=client.Movers.SortOrder[sort] if sort else None,
        frequency=client.Movers.Frequency[frequency] if frequency else None,
    )


@register
async def get_instruments(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol or search term to find instruments"],
    projection: Annotated[
        str,
        (
            "Search method or data type to return (SYMBOL_SEARCH, SYMBOL_REGEX, "
            "DESCRIPTION_SEARCH, DESCRIPTION_REGEX, SEARCH, FUNDAMENTAL)"
        ),
    ] = "symbol-search",
) -> str:
    """
    Search for instruments with a specific symbol.

    Projection can be one of the following:
      SYMBOL_SEARCH
      SYMBOL_REGEX
      DESCRIPTION_SEARCH
      DESCRIPTION_REGEX
      SEARCH
      FUNDAMENTAL

    <example>
    # Search for instruments with the symbol "AAPL"
    get_instruments("AAPL")
    </example>

    <example>
    # Search for AAPL options
    get_instruments("AAPL .*", "symbol-regex")
    </example>

    <example>
    # Return the fundamental data for AAPL
    get_instruments("AAPL", "fundamental")
    </example>
    """
    return await call(
        client.get_instruments,
        symbol,
        projection=client.Instrument.Projection[projection],
    )
