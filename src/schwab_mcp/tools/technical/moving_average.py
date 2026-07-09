"""Moving average indicator tools: SMA, EMA, WMA, and others."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import pandas as pd
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
    compute_window,
    pandas_ta,
)

__all__ = ["register"]


async def moving_average(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute the SMA and EMA"] = 20,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute both the simple and exponential moving averages for Schwab price history."""
    if length <= 0:
        raise ValueError("length must be a positive integer")

    def indicator_fn(frame: pd.DataFrame) -> pd.DataFrame:
        close = frame["close"]
        combined = pd.DataFrame(
            {
                f"sma_{length}": pandas_ta.sma(close, length=length),
                f"ema_{length}": pandas_ta.ema(close, length=length),
            }
        )
        # Drop rows where either series hasn't warmed up yet so every
        # returned row includes both sma_{length} and ema_{length}.
        return combined.dropna(how="any")

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=indicator_fn,
        indicator_name="moving_average",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=2, min_padding=10),
        points=points,
        extra_metadata={"length": length},
    )


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register moving average tools with the MCP server."""
    _ = allow_write
    register_tool(server, moving_average, result_transform=result_transform)
