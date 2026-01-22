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
    compute_window,
    ensure_columns,
    fetch_price_frame,
    pandas_ta,
    series_to_json,
)

__all__ = ["register"]


async def vwap(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int | None, "Optional period applied to VWAP"] = None,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute the Volume Weighted Average Price (VWAP)."""
    if length is not None and length <= 0:
        raise ValueError("length must be positive when provided")

    bars = compute_window(length, multiplier=3, min_padding=20) if length else None

    frame, metadata = await fetch_price_frame(
        ctx, symbol, interval=interval, start=start, end=end, bars=bars
    )

    ensure_columns(frame, ("high", "low", "close", "volume"))

    volume = frame["volume"].astype(float)
    positive_volume_mask = volume.notna() & (volume > 0)
    if not positive_volume_mask.any():
        raise ValueError(
            "Price history includes no positive volume, so VWAP cannot be computed."
        )

    frame = frame.loc[positive_volume_mask].copy()

    vwap_series = pandas_ta.vwap(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        volume=frame["volume"],
        length=length,
    )
    if vwap_series is None:
        raise RuntimeError("pandas_ta_classic.vwap returned no values.")

    vwap_series = vwap_series.dropna()
    if vwap_series.empty:
        raise ValueError("Not enough price history to compute VWAP.")

    default_points = length if length is not None else 30
    values = series_to_json(
        vwap_series,
        limit=points if points is not None else default_points,
        value_key="vwap",
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


async def pivot_points(
    ctx: SchwabContext,
    symbol: Symbol,
    method: Annotated[
        str,
        "Pivot calculation method (standard, fibonacci, camarilla, woodie, demark).",
    ] = "standard",
    lookback: Annotated[int | None, "Number of prior periods to consider"] = None,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute pivot point support and resistance levels."""
    if lookback is not None and lookback <= 0:
        raise ValueError("lookback must be positive when provided")

    bars = compute_window(lookback, multiplier=5, min_padding=20) if lookback else None

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.pivot_points(
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            method=method,
            lookback=lookback,
        ),
        indicator_name="pivot_points",
        interval=interval,
        start=start,
        end=end,
        bars=bars or 50,
        points=points,
        default_points=lookback if lookback is not None else 10,
        required_columns=("high", "low", "close"),
        extra_metadata={"method": method, "lookback": lookback},
    )


async def bollinger_bands(
    ctx: SchwabContext,
    symbol: Symbol,
    length: Annotated[int, "Number of periods used to compute the middle band"] = 20,
    std_dev: Annotated[float, "Standard deviation multiplier"] = 2.0,
    ma_mode: Annotated[str, "Moving average mode (e.g. sma, ema)"] = "sma",
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    points: Points = None,
) -> JSONType:
    """Compute Bollinger Bands for Schwab price history."""
    if length <= 1:
        raise ValueError("length must be greater than 1 for Bollinger Bands")
    if std_dev <= 0:
        raise ValueError("std_dev must be positive")

    return await compute_frame_indicator(
        ctx,
        symbol,
        indicator_fn=lambda frame: pandas_ta.bbands(
            frame["close"],
            length=length,
            std=std_dev,
            mamode=ma_mode,
        ),
        indicator_name="bbands",
        interval=interval,
        start=start,
        end=end,
        bars=compute_window(length, multiplier=3, min_padding=20),
        points=points,
        default_points=length,
        extra_metadata={"length": length, "std_dev": std_dev, "ma_mode": ma_mode},
    )


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    register_tool(server, vwap, result_transform=result_transform)
    register_tool(server, pivot_points, result_transform=result_transform)
    register_tool(server, bollinger_bands, result_transform=result_transform)
