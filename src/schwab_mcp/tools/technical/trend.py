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
    compute_frame_indicator,
    compute_series_indicator,
    compute_window,
    pandas_ta,
)

__all__ = ["register"]


async def macd(
    ctx: SchwabContext,
    symbol: Symbol,
    fast_length: Annotated[int, "Number of fast EMA periods"] = 12,
    slow_length: Annotated[int, "Number of slow EMA periods"] = 26,
    signal_length: Annotated[int, "Signal line EMA periods"] = 9,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the Moving Average Convergence Divergence (MACD) indicator."""
    if fast_length <= 0 or slow_length <= 0 or signal_length <= 0:
        raise ValueError("MACD lengths must be positive integers")
    if fast_length >= slow_length:
        raise ValueError("fast_length must be less than slow_length")

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.macd(
            frame["close"],
            fast=fast_length,
            slow=slow_length,
            signal=signal_length,
        ),
        indicator_name="macd",
        interval=interval,
        start=start,
        end=end,
        bars=max(slow_length * 5, slow_length + signal_length + 20),
        points=points,
        default_points=slow_length,
        extra_metadata={
            "fast_length": fast_length,
            "slow_length": slow_length,
            "signal_length": signal_length,
        },
    )


async def atr(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute ATR"] = 14,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the Average True Range (ATR) for Schwab price history."""
    if length <= 0:
        raise ValueError("length must be a positive integer")

    return await compute_series_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.atr(
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            length=length,
        ),
        indicator_name="atr",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=4, min_padding=20),
        points=points,
        default_points=length,
        value_key=f"atr_{length}",
        required_columns=("high", "low", "close"),
        extra_metadata={"length": length},
    )


async def adx(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute ADX"] = 14,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the Average Directional Index (ADX) for Schwab price history."""
    if length <= 0:
        raise ValueError("length must be a positive integer")

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.adx(
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            length=length,
        ),
        indicator_name="adx",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=4, min_padding=20),
        points=points,
        default_points=length,
        required_columns=("high", "low", "close"),
        extra_metadata={"length": length},
    )


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
