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
        ),
    ] = None,
    frequency_type: Annotated[
        str | None, "The type of frequency with which a new candle is formed"
    ] = None,
    frequency: Annotated[
        str | None, "The number of the frequencyType to be included in each candle"
    ] = None,
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with advanced period and frequency options.

    Period type options:
      DAY - For intraday data
      MONTH - For data spanning months
      YEAR - For yearly data
      YEAR_TO_DATE - For current year-to-date data

    Period options (by period_type):
      DAY: ONE_DAY, TWO_DAYS, THREE_DAYS, FOUR_DAYS, FIVE_DAYS, TEN_DAYS (default)
      MONTH: ONE_MONTH (default), TWO_MONTHS, THREE_MONTHS, SIX_MONTHS
      YEAR: ONE_YEAR (default), TWO_YEARS, THREE_YEARS, FIVE_YEARS, TEN_YEARS, FIFTEEN_YEARS, TWENTY_YEARS
      YEAR_TO_DATE: YEAR_TO_DATE (default)

    Frequency type options (by period_type):
      DAY: MINUTE (default)
      MONTH: DAILY, WEEKLY (default)
      YEAR: DAILY, WEEKLY, MONTHLY (default)
      YEAR_TO_DATE: DAILY, WEEKLY (default)

    If start_datetime and end_datetime are provided, period will be ignored.
    """
    if start_datetime is not None:
        start_datetime = datetime.datetime.fromisoformat(start_datetime)

    if end_datetime is not None:
        end_datetime = datetime.datetime.fromisoformat(end_datetime)

    return await call(
        client.get_advanced_price_history,
        symbol,
        period_type=client.PriceHistory.PeriodType[period_type]
        if period_type
        else None,
        period=client.PriceHistory.Period[period] if period else None,
        frequency_type=client.PriceHistory.FrequencyType[frequency_type]
        if frequency_type
        else None,
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with minute frequency.

    Returns OHLCV data for each minute of trading. Used for detailed intraday
    analysis of short-term price movements. Each candle represents one minute.

    Provides up to 48 days of history. For longer periods, use daily or weekly data.
    Dates should be in ISO format (e.g., '2023-01-01T09:30:00').
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with five minute frequency.

    Returns OHLCV data for each 5-minute period. Provides a balance between
    detailed intraday information and reduced noise compared to minute data.

    Provides approximately nine months of history.
    Dates should be in ISO format (e.g., '2023-01-01T09:30:00').
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with ten minute frequency.

    Returns OHLCV data for each 10-minute period. Good balance between detail
    and noise reduction for intraday trend analysis and support/resistance levels.

    Provides approximately nine months of history.
    Dates should be in ISO format (e.g., '2023-01-01T09:30:00').
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with fifteen minute frequency.

    Returns OHLCV data for each 15-minute period. Strikes a balance between showing
    significant intraday moves while filtering out short-term noise.

    Provides approximately nine months of history.
    Dates should be in ISO format (e.g., '2023-01-01T09:30:00').
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with thirty minute frequency.

    Returns OHLCV data for each 30-minute period. Useful for broader intraday trends
    and patterns while filtering out short-term price fluctuations.

    Provides approximately nine months of history.
    Dates should be in ISO format (e.g., '2023-01-01T09:30:00').
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
    symbol: Annotated[str, "Symbol of the security to fetch price history for"],
    start_datetime: Annotated[
        str | None,
        "Start date for the history in ISO format (e.g., '2023-01-01T00:00:00')",
    ] = None,
    end_datetime: Annotated[
        str | None,
        "End date for the history in ISO format (e.g., '2023-12-31T23:59:59')",
    ] = None,
    extended_hours: Annotated[
        bool | None, "Include pre-market and after-hours trading data"
    ] = None,
    previous_close: Annotated[
        bool | None, "Include the previous market day's closing price"
    ] = None,
) -> str:
    """
    Get price history with daily frequency.

    Returns OHLCV data for each trading day. Useful for medium to long-term analysis,
    trend identification, and technical patterns that develop over multiple days.

    Provides extensive historical coverage (back to 1985 for some securities).
    Dates should be in ISO format (e.g., '2023-01-01T00:00:00').
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
    start_datetime: Annotated[
        str | None, "Start date for the history in ISO format"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for the history in ISO format"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> str:
    """
    Get price history with weekly frequency.

    Returns OHLCV data for each week of trading. Useful for long-term trend analysis,
    position trading, and identifying major market cycles with reduced noise.

    Provides extensive historical coverage (back to 1985 for some securities).
    Dates should be in ISO format (e.g., '2023-01-01T00:00:00').
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
