#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_advanced_price_history(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    period_type: Annotated[str | None, "The type of period to show"] = None,
    period: Annotated[
        str | None,
        (
            "The number of periods to show. Should not be provided if start "
            "and end is provided"
        )
    ] = None,
    frequency_type: Annotated[str | None, "The type of frequency with which a new candle is formed"] = None,
    frequency: Annotated[str | None, "The number of the frequencyType to be included in each candle"] = None,
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get advanced price history for a specific symbol. This function should only be used
    when advanced parameters are needed. For simple price history fetching, use one of
    the other functions.

    Period type can be one of the following:
      DAY
      MONTH
      YEAR
      YEAR_TO_DATE

    Period can be one of the following:
      For DAY period type:
        ONE_DAY
        TWO_DAYS
        THREE_DAYS
        FOUR_DAYS
        FIVE_DAYS
        TEN_DAYS
       If the period is not specified and the periodType is DAY, the default is TEN_DAYS.

      For MONTH period type:
        ONE_MONTH
        TWO_MONTHS
        THREE_MONTHS
        SIX_MONTHS
       If the period is not specified and the periodType is MONTH, the default is ONE_MONTHS.

      For YEAR period type:
        ONE_YEAR
        TWO_YEARS
        THREE_YEARS
        FIVE_YEARS
        TEN_YEARS
        FIFTEEN_YEARS
        TWENTY_YEARS
       If the period is not specified and the periodType is YEAR, the default is ONE_YEAR.

      For YEAR_TO_DATE period type:
        YEAR_TO_DATE
      If the period is not specified and the periodType is YEAR_TO_DATE, the default is YEAR_TO_DATE.

    Frequency type can be one of the following:
      If the period type is DAY:
        MINUTE
      If frequencyType is not specified, and the period type is DAY, the default is MINUTE.

      If the period type is MONTH:
        DAILY
        WEEKLY
      If frequencyType is not specified, and the period type is MONTH, the default is WEEKLY.

      If the period type is YEAR:
        DAILY
        WEEKLY
        MONTHLY
      If frequencyType is not specified, and the period type is YEAR, the default is MONTHLY.

      If the period type is YEAR_TO_DATE:
        DAILY
        WEEKLY
      If frequencyType is not specified, and the period type is YEAR_TO_DATE, the default is WEEKLY.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_advanced_price_history,
        symbol,
        period_type=client.PriceHistory.PeriodType[period_type] if period_type else None,
        period=client.PriceHistory.Period[period] if period else None,
        frequency_type=client.PriceHistory.FrequencyType[frequency_type] if frequency_type else None,
        frequency=frequency,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_minute(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with minute frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_minute,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_five_minutes(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with five minute frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_five_minutes,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_ten_minutes(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with ten minute frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_ten_minutes,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_fifteen_minutes(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with fifteen minute frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_fifteen_minutes,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_thirty_minutes(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with thirty minute frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_thirty_minutes,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_day(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with daily frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_day,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )


@register
async def get_price_history_every_week(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[str | None, "Start date for the history in ISO format"] = None,
    end_datetime: Annotated[str | None, "End date for the history in ISO format"] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history for a specific symbol with weekly frequency.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_price_history_every_week,
        symbol,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        extended_hours=extended_hours,
        previous_close=previous_close,
    )
