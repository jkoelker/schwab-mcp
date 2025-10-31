from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType

from .base import fetch_price_frame, pandas_ta, series_to_json

__all__ = ["register"]


Calculator = Callable[..., Any]


async def _moving_average(
    calculator: Calculator,
    *,
    name: str,
    ctx: SchwabContext,
    symbol: str,
    length: int,
    interval: str,
    start: str | None,
    end: str | None,
    points: int | None,
) -> JSONType:
    if length <= 0:
        raise ValueError("length must be a positive integer")

    padding = max(length // 2, 10)
    window = max(length + padding, length * 2)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window,
    )

    if frame.empty or "close" not in frame.columns:
        raise ValueError("No closing price data returned for the requested inputs.")

    series = calculator(frame["close"], length=length)
    if series is None:
        raise RuntimeError(f"pandas_ta_classic.{name} returned no values.")

    series = series.dropna()
    if series.empty:
        raise ValueError(
            "Not enough price history to compute the requested moving average."
        )

    values = series_to_json(
        series,
        limit=points if points is not None else length,
        value_key=f"{name}_{length}",
    )

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "length": length,
        "start": metadata["start"],
        "end": metadata["end"],
        "values": values,
        "candles": metadata["candles_returned"],
    }


async def sma(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int, "Number of periods used to compute the SMA"] = 20,
    interval: Annotated[
        str,
        ("Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w."),
    ] = "1d",
    start: Annotated[
        str | None,
        (
            "Optional ISO-8601 timestamp for the first candle used in the calculation. "
            "Defaults to enough history based on the requested length."
        ),
    ] = None,
    end: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
    ] = None,
    points: Annotated[
        int | None,
        (
            "Limit the number of SMA values returned. Defaults to the requested length. "
            "Use a larger number to inspect more history."
        ),
    ] = None,
) -> JSONType:
    """Compute a simple moving average for Schwab price history."""

    return await _moving_average(
        pandas_ta.sma,
        name="sma",
        ctx=ctx,
        symbol=symbol,
        length=length,
        interval=interval,
        start=start,
        end=end,
        points=points,
    )


async def ema(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int, "Number of periods used to compute the EMA"] = 20,
    interval: Annotated[
        str,
        ("Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w."),
    ] = "1d",
    start: Annotated[
        str | None,
        (
            "Optional ISO-8601 timestamp for the first candle used in the calculation. "
            "Defaults to enough history based on the requested length."
        ),
    ] = None,
    end: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
    ] = None,
    points: Annotated[
        int | None,
        (
            "Limit the number of EMA values returned. Defaults to the requested length. "
            "Use a larger number to inspect more history."
        ),
    ] = None,
) -> JSONType:
    """Compute an exponential moving average for Schwab price history."""

    return await _moving_average(
        pandas_ta.ema,
        name="ema",
        ctx=ctx,
        symbol=symbol,
        length=length,
        interval=interval,
        start=start,
        end=end,
        points=points,
    )


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    register_tool(server, sma, result_transform=result_transform)
    register_tool(server, ema, result_transform=result_transform)
