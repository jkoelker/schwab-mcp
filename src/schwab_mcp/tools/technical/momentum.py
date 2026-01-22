from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType

from .base import (
    EndTime,
    Interval,
    Points,
    StartTime,
    Symbol,
    ensure_columns,
    fetch_price_frame,
    frame_to_json,
    pandas_ta,
    series_to_json,
)

__all__ = ["register"]


async def rsi(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute the RSI"] = 14,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the Relative Strength Index (RSI) for Schwab price history."""

    if length <= 1:
        raise ValueError("length must be greater than 1 for RSI")

    padding = max(length, 20)
    window = max(length + padding, length * 3)

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

    rsi_series = pandas_ta.rsi(frame["close"], length=length)
    if rsi_series is None:
        raise RuntimeError("pandas_ta_classic.rsi returned no values.")

    rsi_series = rsi_series.dropna()
    if rsi_series.empty:
        raise ValueError("Not enough price history to compute the requested RSI.")

    values = series_to_json(
        rsi_series,
        limit=points if points is not None else length,
        value_key=f"rsi_{length}",
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


async def stoch(
    ctx: SchwabContext,
    symbol: Symbol,
    k_length: Annotated[int, "Number of periods used to compute %K"] = 14,
    d_length: Annotated[int, "Smoothing periods for %D"] = 3,
    smooth_k: Annotated[int, "Smoothing applied to %K before %D"] = 3,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the stochastic oscillator (%K and %D) for Schwab price history."""

    if k_length <= 1:
        raise ValueError("k_length must be greater than 1")
    if d_length <= 0 or smooth_k <= 0:
        raise ValueError("d_length and smooth_k must be positive integers")

    longest = max(k_length, d_length + smooth_k)
    padding = max(smooth_k, 5)
    window = max(longest + padding, longest * 3)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window,
    )

    ensure_columns(frame, ("high", "low", "close"))

    stoch_frame = pandas_ta.stoch(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        k=k_length,
        d=d_length,
        smooth_k=smooth_k,
    )
    if stoch_frame is None:
        raise RuntimeError("pandas_ta_classic.stoch returned no values.")

    stoch_frame = stoch_frame.dropna(how="all")
    if stoch_frame.empty:
        raise ValueError(
            "Not enough price history to compute the stochastic oscillator."
        )

    values = frame_to_json(
        stoch_frame,
        limit=points if points is not None else k_length,
    )

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "k_length": k_length,
        "d_length": d_length,
        "smooth_k": smooth_k,
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
    register_tool(server, rsi, result_transform=result_transform)
    register_tool(server, stoch, result_transform=result_transform)
