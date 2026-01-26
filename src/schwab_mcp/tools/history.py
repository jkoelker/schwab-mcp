#

from collections.abc import Callable
from typing import Annotated, Any

import datetime
from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call


def _parse_iso_datetime(value: str | None) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value is not None else None


async def _get_price_history(
    ctx: SchwabContext,
    method_name: str,
    symbol: str,
    start_datetime: str | None,
    end_datetime: str | None,
    extended_hours: bool | None,
    previous_close: bool | None,
) -> JSONType:
    """Internal helper to fetch price history using the specified client method."""
    client = ctx.price_history
    method = getattr(client, method_name)

    start_dt = _parse_iso_datetime(start_datetime)
    end_dt = _parse_iso_datetime(end_datetime)

    return await call(
        method,
        symbol,
        start_datetime=start_dt,
        end_datetime=end_dt,
        need_extended_hours_data=extended_hours,
        need_previous_close=previous_close,
    )


async def get_advanced_price_history(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    period_type: Annotated[
        str | None, "Period type: DAY, MONTH, YEAR, YEAR_TO_DATE"
    ] = None,
    period: Annotated[
        str | None,
        (
            "Number of periods (e.g., TEN_DAYS, ONE_MONTH, FIVE_YEARS). Varies by period_type. "
            "Ignored if start/end datetimes provided."
        ),
    ] = None,
    frequency_type: Annotated[
        str | None,
        "Frequency type: MINUTE (for DAY), DAILY/WEEKLY (for MONTH/YTD), DAILY/WEEKLY/MONTHLY (for YEAR)",
    ] = None,
    frequency: Annotated[
        int | str | None,
        "Number of frequencyType per candle (e.g., 1, 5, 10 for MINUTE). Strings are coerced to int.",
    ] = None,
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-31T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get price history with advanced period/frequency options. Specify period/frequency OR start/end datetimes.

    Period type options: DAY, MONTH, YEAR, YEAR_TO_DATE
    Period options (by period_type):
      DAY: ONE_DAY, TWO_DAYS, ..., TEN_DAYS (default)
      MONTH: ONE_MONTH (default), TWO_MONTHS, ..., SIX_MONTHS
      YEAR: ONE_YEAR (default), TWO_YEARS, ..., TWENTY_YEARS
      YEAR_TO_DATE: YEAR_TO_DATE (default)
    Frequency type options (by period_type):
      DAY: MINUTE (default)
      MONTH: DAILY, WEEKLY (default)
      YEAR: DAILY, WEEKLY, MONTHLY (default)
      YEAR_TO_DATE: DAILY, WEEKLY (default)
    Dates must be in ISO format.
    """
    client = ctx.price_history

    start_dt = _parse_iso_datetime(start_datetime)
    end_dt = _parse_iso_datetime(end_datetime)

    # Normalize enum-like strings
    period_type_enum = (
        client.PriceHistory.PeriodType[period_type.upper()] if period_type else None
    )
    period_enum = client.PriceHistory.Period[period.upper()] if period else None
    frequency_type_enum = (
        client.PriceHistory.FrequencyType[frequency_type.upper()]
        if frequency_type
        else None
    )

    # Coerce frequency to int if provided as string
    if isinstance(frequency, str):
        frequency = int(frequency)

    return await call(
        client.get_price_history,
        symbol,
        period_type=period_type_enum,
        period=period_enum,
        frequency_type=frequency_type_enum,
        frequency=frequency,
        start_datetime=start_dt,
        end_datetime=end_dt,
        need_extended_hours_data=extended_hours,
        need_previous_close=previous_close,
    )


async def get_price_history_every_minute(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-01T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get OHLCV price history per minute. For detailed intraday analysis. Max 48 days history. Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_minute",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_five_minutes(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-01T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get OHLCV price history per 5 minutes. Balance between detail and noise. Approx. 9 months history. Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_five_minutes",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_ten_minutes(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-01T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get OHLCV price history per 10 minutes. Good for intraday trends/levels. Approx. 9 months history. Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_ten_minutes",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_fifteen_minutes(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-01T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get OHLCV price history per 15 minutes. Shows significant intraday moves, filters noise. Approx. 9 months history. Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_fifteen_minutes",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_thirty_minutes(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T09:30:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-01-01T16:00:00')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get OHLCV price history per 30 minutes. For broader intraday trends, filters noise. Approx. 9 months history. Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_thirty_minutes",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_day(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security to fetch price history for"],
    start_datetime: Annotated[
        str | None,
        "Start date for history (ISO format, e.g., '2023-01-01T00:00:00')",
    ] = None,
    end_datetime: Annotated[
        str | None,
        "End date for history (ISO format, e.g., '2023-12-31T23:59:59')",
    ] = None,
    extended_hours: Annotated[
        bool | None, "Include pre-market and after-hours trading data"
    ] = None,
    previous_close: Annotated[
        bool | None, "Include the previous market day's closing price"
    ] = None,
) -> JSONType:
    """
    Get daily OHLCV price history. For medium/long-term analysis. Extensive history (back to 1985 possible). Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_day",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


async def get_price_history_every_week(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    start_datetime: Annotated[
        str | None, "Start date for history (ISO format, e.g., '2023-01-01T00:00:00')"
    ] = None,
    end_datetime: Annotated[
        str | None, "End date for history (ISO format, e.g., '2023-12-31T23:59:59')"
    ] = None,
    extended_hours: Annotated[bool | None, "Include extended hours data"] = None,
    previous_close: Annotated[bool | None, "Include previous close data"] = None,
) -> JSONType:
    """
    Get weekly OHLCV price history. For long-term analysis, major cycles. Extensive history (back to 1985 possible). Dates ISO format.
    """
    return await _get_price_history(
        ctx,
        "get_price_history_every_week",
        symbol,
        start_datetime,
        end_datetime,
        extended_hours,
        previous_close,
    )


_READ_ONLY_TOOLS = (
    get_advanced_price_history,
    get_price_history_every_minute,
    get_price_history_every_five_minutes,
    get_price_history_every_ten_minutes,
    get_price_history_every_fifteen_minutes,
    get_price_history_every_thirty_minutes,
    get_price_history_every_day,
    get_price_history_every_week,
)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
