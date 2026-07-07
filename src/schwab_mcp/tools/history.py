#

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call, parse_datetime


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

    For intraday candles use frequency_type=MINUTE with frequency 1/5/10/15/30.
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

    start_dt = parse_datetime(start_datetime)
    end_dt = parse_datetime(end_datetime)

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


_READ_ONLY_TOOLS = (get_advanced_price_history,)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
