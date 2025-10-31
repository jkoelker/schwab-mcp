from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType

from .base import (
    ensure_columns,
    fetch_price_frame,
    frame_to_json,
    pandas_ta,
    series_to_json,
)

__all__ = ["register"]


async def macd(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    fast_length: Annotated[int, "Number of fast EMA periods"] = 12,
    slow_length: Annotated[int, "Number of slow EMA periods"] = 26,
    signal_length: Annotated[int, "Signal line EMA periods"] = 9,
    interval: Annotated[
        str,
        ("Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w."),
    ] = "1d",
    start: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the first candle used in the calculation.",
    ] = None,
    end: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
    ] = None,
    points: Annotated[
        int | None,
        (
            "Limit the number of MACD values returned. Defaults to the slow_length. "
            "Use a larger number to inspect more history."
        ),
    ] = None,
) -> JSONType:
    """Compute the Moving Average Convergence Divergence (MACD) indicator."""

    if fast_length <= 0 or slow_length <= 0 or signal_length <= 0:
        raise ValueError("MACD lengths must be positive integers")
    if fast_length >= slow_length:
        raise ValueError("fast_length must be less than slow_length")

    window = max(slow_length * 5, slow_length + signal_length + 20)

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

    macd_frame = pandas_ta.macd(
        frame["close"],
        fast=fast_length,
        slow=slow_length,
        signal=signal_length,
    )
    if macd_frame is None:
        raise RuntimeError("pandas_ta_classic.macd returned no values.")

    macd_frame = macd_frame.dropna(how="all")
    if macd_frame.empty:
        raise ValueError("Not enough price history to compute MACD.")

    values = frame_to_json(
        macd_frame,
        limit=points if points is not None else slow_length,
    )

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "fast_length": fast_length,
        "slow_length": slow_length,
        "signal_length": signal_length,
        "start": metadata["start"],
        "end": metadata["end"],
        "values": values,
        "candles": metadata["candles_returned"],
    }


async def atr(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int, "Number of periods used to compute ATR"] = 14,
    interval: Annotated[
        str,
        ("Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w."),
    ] = "1d",
    start: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the first candle used in the calculation.",
    ] = None,
    end: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
    ] = None,
    points: Annotated[
        int | None,
        ("Limit the number of ATR values returned. Defaults to the requested length."),
    ] = None,
) -> JSONType:
    """Compute the Average True Range (ATR) for Schwab price history."""

    if length <= 0:
        raise ValueError("length must be a positive integer")

    window = max(length * 4, length + 20)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window,
    )

    ensure_columns(frame, ("high", "low", "close"))

    atr_series = pandas_ta.atr(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        length=length,
    )
    if atr_series is None:
        raise RuntimeError("pandas_ta_classic.atr returned no values.")

    atr_series = atr_series.dropna()
    if atr_series.empty:
        raise ValueError("Not enough price history to compute ATR.")

    values = series_to_json(
        atr_series,
        limit=points if points is not None else length,
        value_key=f"atr_{length}",
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


async def adx(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int, "Number of periods used to compute ADX"] = 14,
    interval: Annotated[
        str,
        ("Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w."),
    ] = "1d",
    start: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the first candle used in the calculation.",
    ] = None,
    end: Annotated[
        str | None,
        "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
    ] = None,
    points: Annotated[
        int | None,
        ("Limit the number of ADX values returned. Defaults to the requested length."),
    ] = None,
) -> JSONType:
    """Compute the Average Directional Index (ADX) for Schwab price history."""

    if length <= 0:
        raise ValueError("length must be a positive integer")

    window = max(length * 4, length + 20)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window,
    )

    ensure_columns(frame, ("high", "low", "close"))

    adx_frame = pandas_ta.adx(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        length=length,
    )
    if adx_frame is None:
        raise RuntimeError("pandas_ta_classic.adx returned no values.")

    adx_frame = adx_frame.dropna(how="all")
    if adx_frame.empty:
        raise ValueError("Not enough price history to compute ADX.")

    values = frame_to_json(
        adx_frame,
        limit=points if points is not None else length,
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


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    register_tool(server, macd, result_transform=result_transform)
    register_tool(server, atr, result_transform=result_transform)
    register_tool(server, adx, result_transform=result_transform)
