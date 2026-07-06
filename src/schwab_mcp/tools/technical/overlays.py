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
    ensure_columns,
    fetch_price_frame,
    pandas_ta,
    series_to_json,
)

__all__ = ["register"]

# pandas_ta_classic (the pinned indicator library, aliased as `pandas_ta` in
# .base) has no `pivot_points` attribute under any version we've run against
# (confirmed empty on 0.3.59 — no top-level function, no submodule), so the
# indicator is computed directly below instead. vwap/bbands still use
# pandas_ta since those genuinely exist there.

_PIVOT_METHODS = ("standard", "fibonacci", "camarilla", "woodie", "demark")


def _compute_pivot_points(
    frame: pd.DataFrame, *, method: str, lookback: int | None
) -> pd.DataFrame:
    """Compute floor-trader pivot levels from the prior period's H/L/C."""
    method = method.lower()
    if method not in _PIVOT_METHODS:
        raise ValueError(
            f"Unsupported pivot method '{method}'. "
            f"Choose from: {', '.join(_PIVOT_METHODS)}."
        )

    window = lookback if lookback and lookback > 0 else 1
    high = frame["high"].rolling(window=window).max().shift(1)
    low = frame["low"].rolling(window=window).min().shift(1)
    close = frame["close"].shift(1)
    diff = high - low

    result = pd.DataFrame(index=frame.index)

    if method == "standard":
        pp = (high + low + close) / 3
        result["PP"] = pp
        result["R1"] = 2 * pp - low
        result["S1"] = 2 * pp - high
        result["R2"] = pp + diff
        result["S2"] = pp - diff
        result["R3"] = high + 2 * (pp - low)
        result["S3"] = low - 2 * (high - pp)
    elif method == "fibonacci":
        pp = (high + low + close) / 3
        result["PP"] = pp
        result["R1"] = pp + 0.382 * diff
        result["S1"] = pp - 0.382 * diff
        result["R2"] = pp + 0.618 * diff
        result["S2"] = pp - 0.618 * diff
        result["R3"] = pp + diff
        result["S3"] = pp - diff
    elif method == "camarilla":
        result["PP"] = (high + low + close) / 3
        result["R1"] = close + diff * 1.1 / 12
        result["S1"] = close - diff * 1.1 / 12
        result["R2"] = close + diff * 1.1 / 6
        result["S2"] = close - diff * 1.1 / 6
        result["R3"] = close + diff * 1.1 / 4
        result["S3"] = close - diff * 1.1 / 4
        result["R4"] = close + diff * 1.1 / 2
        result["S4"] = close - diff * 1.1 / 2
    elif method == "woodie":
        pp = (high + low + 2 * close) / 4
        result["PP"] = pp
        result["R1"] = 2 * pp - low
        result["S1"] = 2 * pp - high
        result["R2"] = pp + diff
        result["S2"] = pp - diff
    else:  # demark
        if "open" not in frame.columns:
            raise ValueError(
                "demark pivot method requires an 'open' column in price history."
            )
        open_ = frame["open"].shift(1)
        x = high + low + 2 * close  # close == open case
        x = x.mask(close < open_, high + 2 * low + close)
        x = x.mask(close > open_, 2 * high + low + close)
        pp = x / 4
        result["PP"] = pp
        result["R1"] = x / 2 - low
        result["S1"] = x / 2 - high

    return result


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
        indicator_fn=lambda frame: _compute_pivot_points(
            frame, method=method, lookback=lookback
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
