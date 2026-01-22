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

    return await compute_series_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.rsi(frame["close"], length=length),
        indicator_name="rsi",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=3, min_padding=20),
        points=points,
        default_points=length,
        value_key=f"rsi_{length}",
        extra_metadata={"length": length},
    )


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

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.stoch(
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            k=k_length,
            d=d_length,
            smooth_k=smooth_k,
        ),
        indicator_name="stoch",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(longest, multiplier=3, min_padding=5),
        points=points,
        default_points=k_length,
        required_columns=("high", "low", "close"),
        extra_metadata={
            "k_length": k_length,
            "d_length": d_length,
            "smooth_k": smooth_k,
        },
    )


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    register_tool(server, rsi, result_transform=result_transform)
    register_tool(server, stoch, result_transform=result_transform)
