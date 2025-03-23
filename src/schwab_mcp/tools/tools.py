#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_datetime() -> str:
    """Get the current datetime in ISO format"""
    return datetime.datetime.now().isoformat()


@register
async def get_market_hours(
    client: schwab.client.AsyncClient,
    markets: Annotated[list[str] | str, "Market to get hours for"],
    date: Annotated[str | None, "Date to get hours for"] = None,
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
    index: Annotated[str, "Index to get movers for"],
    sort: Annotated[str, "Sort by a particular attribute"] = None,
    frequency: Annotated[str, "Only return movers that saw this magnitude of change or greater"] = None,
) -> str:
    """
    Get movers for a specific index.

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
