from __future__ import annotations

from typing import Annotated

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


async def vwap(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int | None, "Optional period applied to VWAP"] = None,
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
            "Limit the number of VWAP values returned. Defaults to the requested length "
            "when provided, otherwise 30."
        ),
    ] = None,
) -> JSONType:
    """Compute the Volume Weighted Average Price (VWAP)."""

    window = 0
    if length is not None:
        if length <= 0:
            raise ValueError("length must be positive when provided")
        window = max(length * 3, length + 20)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window if window else None,
    )

    ensure_columns(frame, ("high", "low", "close", "volume"))

    volume = frame["volume"].astype(float)
    positive_volume_mask = volume.notna() & (volume > 0)
    if not positive_volume_mask.any():
        raise ValueError(
            "Price history includes no positive volume, so VWAP cannot be computed for this symbol."
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
    symbol: Annotated[str, "Symbol of the security"],
    method: Annotated[
        str,
        "Pivot calculation method (standard, fibonacci, camarilla, woodie, demark).",
    ] = "standard",
    lookback: Annotated[int | None, "Number of prior periods to consider"] = None,
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
            "Limit the number of pivot levels returned. Defaults to lookback or 10 if unset."
        ),
    ] = None,
) -> JSONType:
    """Compute pivot point support and resistance levels."""

    if lookback is not None and lookback <= 0:
        raise ValueError("lookback must be positive when provided")

    window = 0
    if lookback is not None:
        window = max(lookback * 5, lookback + 20)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window if window else None,
    )

    ensure_columns(frame, ("high", "low", "close"))

    pivot_frame = pandas_ta.pivot_points(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        method=method,
        lookback=lookback,
    )
    if pivot_frame is None:
        raise RuntimeError("pandas_ta_classic.pivot_points returned no values.")

    pivot_frame = pivot_frame.dropna(how="all")
    if pivot_frame.empty:
        raise ValueError("Not enough price history to compute pivot points.")

    default_points = lookback if lookback is not None else 10
    values = frame_to_json(
        pivot_frame,
        limit=points if points is not None else default_points,
    )

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "method": method,
        "lookback": lookback,
        "start": metadata["start"],
        "end": metadata["end"],
        "values": values,
        "candles": metadata["candles_returned"],
    }


async def bollinger_bands(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the security"],
    length: Annotated[int, "Number of periods used to compute the middle band"] = 20,
    std_dev: Annotated[float, "Standard deviation multiplier"] = 2.0,
    ma_mode: Annotated[str, "Moving average mode (e.g. sma, ema)"] = "sma",
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
        ("Limit the number of band values returned. Defaults to the requested length."),
    ] = None,
) -> JSONType:
    """Compute Bollinger Bands for Schwab price history."""

    if length <= 1:
        raise ValueError("length must be greater than 1 for Bollinger Bands")
    if std_dev <= 0:
        raise ValueError("std_dev must be positive")

    window = max(length * 3, length + 20)

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

    bands = pandas_ta.bbands(
        frame["close"],
        length=length,
        std=std_dev,
        mamode=ma_mode,
    )
    if bands is None:
        raise RuntimeError("pandas_ta_classic.bbands returned no values.")

    bands = bands.dropna(how="all")
    if bands.empty:
        raise ValueError("Not enough price history to compute Bollinger Bands.")

    values = frame_to_json(
        bands,
        limit=points if points is not None else length,
    )

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "length": length,
        "std_dev": std_dev,
        "ma_mode": ma_mode,
        "start": metadata["start"],
        "end": metadata["end"],
        "values": values,
        "candles": metadata["candles_returned"],
    }


def register(server: FastMCP, *, allow_write: bool) -> None:
    _ = allow_write
    register_tool(server, vwap)
    register_tool(server, pivot_points)
    register_tool(server, bollinger_bands)
