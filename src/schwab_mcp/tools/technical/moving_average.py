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
    compute_series_indicator,
    compute_window,
    pandas_ta,
)

__all__ = ["register"]


async def sma(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute the SMA"] = 20,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute a simple moving average for Schwab price history."""
    if length <= 0:
        raise ValueError("length must be a positive integer")

    return await compute_series_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.sma(frame["close"], length=length),
        indicator_name="sma",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=2, min_padding=10),
        points=points,
        default_points=length,
        value_key=f"sma_{length}",
        extra_metadata={"length": length},
    )


async def ema(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute the EMA"] = 20,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute an exponential moving average for Schwab price history."""
    if length <= 0:
        raise ValueError("length must be a positive integer")

    return await compute_series_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.ema(frame["close"], length=length),
        indicator_name="ema",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=2, min_padding=10),
        points=points,
        default_points=length,
        value_key=f"ema_{length}",
        extra_metadata={"length": length},
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
