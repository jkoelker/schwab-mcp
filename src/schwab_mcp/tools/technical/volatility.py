from __future__ import annotations

import datetime as _dt
import math
from typing import Annotated, Any, Callable, Mapping, cast

import numpy as np
import pandas as pd
from mcp.server.fastmcp import FastMCP
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call

from .base import (
    EndTime,
    Interval,
    StartTime,
    Symbol,
    compute_window,
    ensure_columns,
    fetch_price_frame,
)

__all__ = ["register"]

_WEEK_DAYS = 5
_MONTH_DAYS = 21


def _volatility_regime(annualized_pct: float) -> str:
    if annualized_pct < 10:
        return "very_low"
    if annualized_pct < 15:
        return "low"
    if annualized_pct < 20:
        return "normal"
    if annualized_pct < 30:
        return "elevated"
    if annualized_pct < 50:
        return "high"
    return "extreme"


def _compute_percentile(vol_series: pd.Series, latest: float) -> float:
    if vol_series.empty:
        return 50.0
    below = (vol_series < latest).sum()
    return float(below / len(vol_series) * 100.0)


def _round(value: float, digits: int = 2) -> float:
    return float(round(value, digits))


async def historical_volatility(
    ctx: SchwabContext,
    symbol: Symbol,
    period: Annotated[int, "Rolling window size for volatility"] = 20,
    interval: Interval = "1d",
    start: StartTime = None,
    end: EndTime = None,
    bars: Annotated[
        int | None,
        (
            "Override the number of candles fetched. Defaults to fetching a padded "
            "window sized for the requested period."
        ),
    ] = None,
    annualize_factor: Annotated[
        int,
        "Trading sessions per year used for annualization (default 252 for US equities).",
    ] = 252,
    method: Annotated[
        str,
        "Volatility method: close_to_close (default), log_returns, or parkinson.",
    ] = "close_to_close",
) -> JSONType:
    """Compute historical volatility statistics for Schwab price history."""

    if period <= 1:
        raise ValueError("period must be greater than 1")
    if annualize_factor <= 0:
        raise ValueError("annualize_factor must be positive")

    method_key = method.strip().lower()
    valid_methods = {"close_to_close", "log_returns", "parkinson"}
    if method_key not in valid_methods:
        raise ValueError(
            "Invalid method. Choose from close_to_close, log_returns, or parkinson."
        )

    required_points = period + 1 if method_key != "parkinson" else period
    window = (
        bars
        if bars is not None
        else compute_window(period, multiplier=2, min_padding=10)
    )
    window = max(window, required_points)

    frame, metadata = await fetch_price_frame(
        ctx,
        symbol,
        interval=interval,
        start=start,
        end=end,
        bars=window,
    )

    if frame.empty:
        raise ValueError("Price history request returned no data.")

    if method_key == "parkinson":
        ensure_columns(frame, ("high", "low"))
        working = frame[["high", "low"]].dropna()
        if len(working) < required_points:
            raise ValueError(
                "Not enough high/low data to compute Parkinson volatility for the requested period."
            )

        hl_ratio = np.log(working["high"] / working["low"])
        hl_ratio_sq = hl_ratio.pow(2)
        rolling_sum = hl_ratio_sq.rolling(window=period, min_periods=period).sum()
        vol_series = (rolling_sum / (period * 4.0 * math.log(2.0))).pow(0.5)
        vol_series = cast(pd.Series, vol_series)
    else:
        ensure_columns(frame, ("close",))
        closes = frame["close"].dropna()
        if len(closes) < required_points:
            raise ValueError(
                "Not enough closing prices to compute historical volatility for the requested period."
            )

        if method_key == "log_returns":
            returns = np.log(closes / closes.shift(1))
        else:
            returns = closes.pct_change()

        returns = returns.dropna()
        if len(returns) < period:
            raise ValueError(
                "Not enough return values to compute historical volatility for the requested period."
            )

        vol_series = returns.rolling(window=period, min_periods=period).std()
        vol_series = cast(pd.Series, vol_series)

    vol_series = vol_series.dropna()
    if vol_series.empty:
        raise ValueError(
            "Unable to compute historical volatility with the provided inputs."
        )

    daily_vol = float(vol_series.iloc[-1])
    daily_vol_pct = daily_vol * 100.0
    weekly_vol_pct = daily_vol * math.sqrt(_WEEK_DAYS) * 100.0
    monthly_vol_pct = daily_vol * math.sqrt(_MONTH_DAYS) * 100.0
    annualized_vol_pct = daily_vol * math.sqrt(annualize_factor) * 100.0

    percentile_rank = _compute_percentile(vol_series, daily_vol)

    if vol_series.empty:
        min_vol = max_vol = mean_vol = 0.0
    else:
        scaled = vol_series * math.sqrt(annualize_factor) * 100.0
        min_vol = float(scaled.min())
        max_vol = float(scaled.max())
        mean_vol = float(scaled.mean())

    return {
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "start": metadata["start"],
        "end": metadata["end"],
        "candles": metadata["candles_returned"],
        "period": period,
        "annualize_factor": annualize_factor,
        "method": method_key,
        "daily_vol": _round(daily_vol_pct),
        "weekly_vol": _round(weekly_vol_pct),
        "monthly_vol": _round(monthly_vol_pct),
        "annualized_vol": _round(annualized_vol_pct),
        "percentile_rank": _round(percentile_rank, 1),
        "regime": _volatility_regime(annualized_vol_pct),
        "min_vol": _round(min_vol),
        "max_vol": _round(max_vol),
        "mean_vol": _round(mean_vol),
    }


async def expected_move(
    ctx: SchwabContext,
    symbol: Symbol,
    call_price: Annotated[float | None, "At-the-money call option premium"] = None,
    put_price: Annotated[float | None, "At-the-money put option premium"] = None,
    interval: Interval = "1d",
    underlying_price: Annotated[
        float | None,
        "Optional underlying price. If omitted, fetches the most recent close.",
    ] = None,
    multiplier: Annotated[
        float,
        "Adjustment multiplier for the straddle (default 0.85 for ~1 std dev).",
    ] = 0.85,
) -> JSONType:
    """Calculate the option-priced ±1 standard deviation move."""

    chain: Mapping[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    if call_price is not None and call_price <= 0:
        raise ValueError("call_price must be a positive value")
    if put_price is not None and put_price <= 0:
        raise ValueError("put_price must be a positive value")
    if multiplier <= 0:
        raise ValueError("multiplier must be a positive value")

    underlying = underlying_price

    needs_chain = call_price is None or put_price is None
    if needs_chain:
        chain = await _fetch_option_chain(ctx, symbol)

        chain_underlying = chain.get("underlyingPrice") if chain else None
        if underlying is None and chain_underlying is not None:
            underlying = float(chain_underlying)

    if underlying is None:
        frame, metadata = await fetch_price_frame(
            ctx,
            symbol,
            interval=interval,
            bars=1,
        )

        if frame.empty or "close" not in frame.columns:
            raise ValueError(
                "Unable to determine the underlying price from price history."
            )

        underlying = float(frame["close"].iloc[-1])

    if underlying <= 0:
        raise ValueError("underlying_price must be positive")

    if needs_chain:
        call_contract, put_contract = _select_atm_contracts(chain, underlying)
        if call_price is None:
            call_price = _option_price(call_contract)
        if put_price is None:
            put_price = _option_price(put_contract)

    if call_price is None or put_price is None:
        raise ValueError("Unable to determine ATM call and put premiums.")

    if call_price <= 0 or put_price <= 0:
        raise ValueError("call_price and put_price must be positive values")

    straddle_price = float(call_price) + float(put_price)
    move_percent = straddle_price / float(underlying)
    adjusted_move = straddle_price * float(multiplier)
    adjusted_move_percent = adjusted_move / float(underlying)

    boundaries = {
        "upper_1x": float(underlying) + adjusted_move,
        "lower_1x": float(underlying) - adjusted_move,
        "upper_2x": float(underlying) + (adjusted_move * 2.0),
        "lower_2x": float(underlying) - (adjusted_move * 2.0),
    }

    response: dict[str, JSONType] = {
        "symbol": symbol.upper(),
        "call_price": float(call_price),
        "put_price": float(put_price),
        "underlying_price": float(underlying),
        "expected_move": straddle_price,
        "expected_move_percent": move_percent,
        "multiplier": float(multiplier),
        "adjusted_move": adjusted_move,
        "adjusted_move_percent": adjusted_move_percent,
        "boundaries": boundaries,
    }

    if metadata is not None:
        response.update(
            {
                "interval": metadata["interval"],
                "start": metadata["start"],
                "end": metadata["end"],
                "candles": metadata["candles_returned"],
            }
        )
    else:
        response["interval"] = interval

    return response


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    register_tool(server, expected_move, result_transform=result_transform)
    register_tool(server, historical_volatility, result_transform=result_transform)


async def _fetch_option_chain(ctx: SchwabContext, symbol: str) -> Mapping[str, Any]:
    response = await call(
        ctx.options.get_option_chain,
        symbol,
        contract_type=None,
        strike_count=10,
        include_underlying_quote=True,
    )

    if not isinstance(response, Mapping):
        raise TypeError("Unexpected option chain response type")

    return cast(Mapping[str, Any], response)


def _select_atm_contracts(
    chain: Mapping[str, Any] | None, underlying: float
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not chain:
        raise ValueError("Option chain response missing")

    call_map = chain.get("callExpDateMap") or {}
    put_map = chain.get("putExpDateMap") or {}

    best: tuple[float, _dt.date, float, Mapping[str, Any], Mapping[str, Any]] | None = (
        None
    )

    for exp_key, strikes in call_map.items():
        exp_date = _parse_expiration(exp_key)
        for strike_key, contracts in strikes.items():
            if not contracts:
                continue
            strike = _to_float(strike_key)
            call_contract = contracts[0]
            put_contract = _get_contract(put_map, exp_key, strike_key)
            if put_contract is None:
                continue

            diff = abs(strike - underlying)
            if best is None or (diff, exp_date, strike) < (best[0], best[1], best[2]):
                best = (diff, exp_date, strike, call_contract, put_contract)

    if best is None:
        raise ValueError("Unable to locate at-the-money call and put contracts.")

    return best[3], best[4]


def _get_contract(
    exp_map: Mapping[str, Any], exp_key: str, strike_key: str
) -> Mapping[str, Any] | None:
    strikes = exp_map.get(exp_key)
    if not strikes:
        return None
    contracts = strikes.get(strike_key)
    if not contracts:
        return None
    return contracts[0]


def _option_price(contract: Mapping[str, Any]) -> float:
    for key in ("mark", "markPrice", "mark_price"):
        value = contract.get(key)
        if _is_positive_number(value):
            return _to_float(value)

    bid = contract.get("bid")
    ask = contract.get("ask")
    if _is_positive_number(bid) and _is_positive_number(ask):
        return (_to_float(bid) + _to_float(ask)) / 2.0

    for key in ("last", "lastPrice", "closePrice"):
        value = contract.get(key)
        if _is_positive_number(value):
            return _to_float(value)

    raise ValueError("Option contract missing price information")


def _parse_expiration(value: str) -> _dt.date:
    date_part = value.split(":", 1)[0]
    return _dt.date.fromisoformat(date_part)


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _is_positive_number(value: Any) -> bool:
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False
