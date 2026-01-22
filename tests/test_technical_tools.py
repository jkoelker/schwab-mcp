import math
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools.technical import (
    base,
    moving_average,
    momentum,
    overlays,
    trend,
    volatility,
)

from conftest import run


def run_tool(coro) -> dict[str, Any]:
    result = run(coro)
    assert isinstance(result, dict)
    return cast(dict[str, Any], result)


@pytest.fixture
def dummy_ctx() -> SchwabContext:
    ctx = SimpleNamespace()
    ctx.options = SimpleNamespace(get_option_chain=object())
    return cast(SchwabContext, ctx)


@pytest.fixture
def price_data():
    index = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    frame = pd.DataFrame({"close": [10, 11, 12, 13, 14, 15]}, index=index)
    start_dt = cast(pd.Timestamp, index[0])
    end_dt = cast(pd.Timestamp, index[-1])
    metadata = {
        "symbol": "HOOD",
        "interval": "1d",
        "start": start_dt.to_pydatetime().isoformat(),
        "end": end_dt.to_pydatetime().isoformat(),
        "bars_requested": None,
        "empty": False,
        "candles_returned": len(frame),
    }
    return frame, metadata


@pytest.fixture
def ohlcv_data():
    index = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [10, 10.5, 11, 12, 13, 14],
            "high": [11, 11.5, 12, 13, 14, 15],
            "low": [9, 9.5, 10, 11, 12, 13],
            "close": [10, 11, 12, 13, 14, 15],
            "volume": [100, 120, 140, 160, 180, 200],
        },
        index=index,
    )
    start_dt = cast(pd.Timestamp, index[0])
    end_dt = cast(pd.Timestamp, index[-1])
    metadata = {
        "symbol": "HOOD",
        "interval": "1d",
        "start": start_dt.to_pydatetime().isoformat(),
        "end": end_dt.to_pydatetime().isoformat(),
        "bars_requested": None,
        "empty": False,
        "candles_returned": len(frame),
    }
    return frame, metadata


def test_sma_returns_expected_values(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        assert ctx is dummy_ctx
        assert symbol == "HOOD"
        assert kwargs["interval"] == "1d"
        return frame, metadata

    def fake_sma(series, *, length):
        return series.rolling(length, min_periods=1).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(sma=fake_sma),
    )

    result = run_tool(moving_average.sma(dummy_ctx, "HOOD", length=3, points=2))

    assert result["symbol"] == "HOOD"
    assert result["interval"] == "1d"
    assert result["candles"] == len(frame)

    values = result["values"]
    assert len(values) == 2
    expected = frame["close"].rolling(3, min_periods=1).mean().tail(2).to_numpy()
    for row, expected_value in zip(values, expected):
        assert row["timestamp"].endswith("+00:00")
        assert row["sma_3"] == pytest.approx(float(expected_value))


def test_ema_defaults_to_length_points(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        assert kwargs["bars"] >= 0
        return frame, metadata

    def fake_ema(series, *, length):
        return series.ewm(span=length, adjust=False).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(ema=fake_ema),
    )

    result = run_tool(moving_average.ema(dummy_ctx, "HOOD", length=4))

    values = result["values"]
    assert len(values) == 4
    last_value = frame["close"].ewm(span=4, adjust=False).mean().iloc[-1]
    assert values[-1]["ema_4"] == pytest.approx(float(last_value))


def test_rsi_returns_expected_values(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_rsi(series, *, length):
        return pd.Series(
            [40.0 + idx for idx in range(len(series))],
            index=series.index,
        )

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        momentum,
        "pandas_ta",
        SimpleNamespace(rsi=fake_rsi),
    )

    result = run_tool(momentum.rsi(dummy_ctx, "HOOD", length=5, points=3))

    values = result["values"]
    assert len(values) == 3
    assert values[-1]["rsi_5"] == pytest.approx(40.0 + len(frame) - 1)


def test_rsi_rejects_short_length(dummy_ctx):
    with pytest.raises(ValueError):
        run(momentum.rsi(dummy_ctx, "HOOD", length=1))


def test_stoch_returns_expected_values(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_stoch(high, low, close, *, k, d, smooth_k):
        values = pd.DataFrame(
            {
                "STOCHk": pd.Series(
                    [40.0, 50.0, 60.0, 70.0, 80.0, 90.0], index=close.index
                ),
                "STOCHd": pd.Series(
                    [35.0, 45.0, 55.0, 65.0, 75.0, 85.0], index=close.index
                ),
            }
        )
        return values

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        momentum,
        "pandas_ta",
        SimpleNamespace(
            stoch=fake_stoch,
            rsi=momentum.pandas_ta.rsi
            if hasattr(momentum.pandas_ta, "rsi")
            else fake_stoch,
        ),
    )

    result = run_tool(
        momentum.stoch(dummy_ctx, "HOOD", k_length=5, d_length=3, smooth_k=3, points=3)
    )

    values = result["values"]
    assert len(values) == 3
    for row in values:
        assert set(row.keys()) == {"timestamp", "STOCHk", "STOCHd"}


def test_vwap_returns_series(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_vwap(high, low, close, volume, *, length=None):
        return pd.Series([100.0 + idx for idx in range(len(close))], index=close.index)

    monkeypatch.setattr(overlays, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(vwap=fake_vwap, pivot_points=None, bbands=None),
    )

    result = run_tool(overlays.vwap(dummy_ctx, "HOOD", length=5, points=2))

    values = result["values"]
    assert len(values) == 2
    assert values[-1]["vwap"] == pytest.approx(100.0 + len(frame) - 1)


def test_vwap_requires_positive_volume(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data
    frame = frame.copy()
    frame["volume"] = 0

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def unexpected_vwap(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("vwap calculation should not be invoked")

    monkeypatch.setattr(overlays, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(vwap=unexpected_vwap, pivot_points=None, bbands=None),
    )

    with pytest.raises(ValueError, match="no positive volume"):
        run(overlays.vwap(dummy_ctx, "HOOD", length=5))


def test_pivot_points_returns_levels(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_pivots(high, low, close, *, method="standard", lookback=None):
        data = pd.DataFrame(
            {
                "pp": pd.Series([10, 11, 12, 13, 14, 15], index=close.index),
                "r1": pd.Series([11, 12, 13, 14, 15, 16], index=close.index),
                "s1": pd.Series([9, 10, 11, 12, 13, 14], index=close.index),
            }
        )
        return data

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(
            pivot_points=fake_pivots,
            vwap=lambda *args, **kwargs: None,
            bbands=lambda *args, **kwargs: None,
        ),
    )

    result = run_tool(
        overlays.pivot_points(
            dummy_ctx, "HOOD", method="standard", lookback=5, points=2
        )
    )

    values = result["values"]
    assert len(values) == 2
    assert {"timestamp", "pp", "r1", "s1"}.issubset(values[-1].keys())


def test_bollinger_bands_returns_values(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_bbands(series, *, length, std, mamode):
        data = pd.DataFrame(
            {
                "BBL": series - 1,
                "BBM": series,
                "BBU": series + 1,
            }
        )
        return data

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(
            bbands=fake_bbands,
            vwap=lambda *args, **kwargs: None,
            pivot_points=lambda *args, **kwargs: None,
        ),
    )

    result = run_tool(overlays.bollinger_bands(dummy_ctx, "HOOD", length=3, points=2))

    values = result["values"]
    assert len(values) == 2
    last = values[-1]
    assert {"timestamp", "BBL", "BBM", "BBU"}.issubset(last.keys())


def test_macd_returns_expected_values(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_macd(series, *, fast, slow, signal):
        data = pd.DataFrame(
            {
                "MACD": pd.Series(range(len(series)), index=series.index),
                "MACDs": pd.Series(range(len(series)), index=series.index) + 1,
            }
        )
        return data

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        trend,
        "pandas_ta",
        SimpleNamespace(
            macd=fake_macd,
            atr=lambda *args, **kwargs: None,
            adx=lambda *args, **kwargs: None,
        ),
    )

    result = run_tool(
        trend.macd(
            dummy_ctx, "HOOD", fast_length=5, slow_length=10, signal_length=3, points=3
        )
    )

    values = result["values"]
    assert len(values) == 3
    assert {"timestamp", "MACD", "MACDs"}.issubset(values[-1].keys())


def test_atr_returns_series(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_atr(high, low, close, *, length):
        return pd.Series([1.0 + idx for idx in range(len(close))], index=close.index)

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        trend,
        "pandas_ta",
        SimpleNamespace(
            atr=fake_atr,
            adx=lambda *args, **kwargs: None,
            macd=lambda *args, **kwargs: None,
        ),
    )

    result = run_tool(trend.atr(dummy_ctx, "HOOD", length=4, points=2))

    values = result["values"]
    assert len(values) == 2
    assert values[-1]["atr_4"] == pytest.approx(1.0 + len(frame) - 1)


def test_adx_returns_frame(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_adx(high, low, close, *, length):
        return pd.DataFrame(
            {
                "ADX": pd.Series([20, 22, 24, 26, 28, 30], index=close.index),
                "DMP": pd.Series([15, 16, 17, 18, 19, 20], index=close.index),
                "DMN": pd.Series([10, 11, 12, 13, 14, 15], index=close.index),
            }
        )

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        trend,
        "pandas_ta",
        SimpleNamespace(
            adx=fake_adx,
            atr=lambda *args, **kwargs: None,
            macd=lambda *args, **kwargs: None,
        ),
    )

    result = run_tool(trend.adx(dummy_ctx, "HOOD", length=5, points=2))

    values = result["values"]
    assert len(values) == 2
    assert {"timestamp", "ADX", "DMP", "DMN"}.issubset(values[-1].keys())


def test_historical_volatility_close_to_close(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        assert kwargs["interval"] == "1d"
        return frame, metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    period = 3
    result = run_tool(
        volatility.historical_volatility(
            dummy_ctx,
            "HOOD",
            period=period,
            method="close_to_close",
        )
    )

    returns = frame["close"].pct_change().dropna()
    vol_series = returns.rolling(window=period, min_periods=period).std().dropna()
    daily_vol = vol_series.iloc[-1]
    percentile = (vol_series < daily_vol).sum() / len(vol_series) * 100.0

    assert result["symbol"] == "HOOD"
    assert result["candles"] == metadata["candles_returned"]
    assert result["method"] == "close_to_close"
    assert result["period"] == period
    assert result["daily_vol"] == pytest.approx(round(daily_vol * 100.0, 2))
    assert result["weekly_vol"] == pytest.approx(
        round(daily_vol * math.sqrt(5) * 100.0, 2)
    )
    assert result["annualized_vol"] == pytest.approx(
        round(daily_vol * math.sqrt(252) * 100.0, 2)
    )
    assert result["percentile_rank"] == pytest.approx(round(percentile, 1))


def test_historical_volatility_parkinson(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    period = 4
    result = run_tool(
        volatility.historical_volatility(
            dummy_ctx,
            "HOOD",
            period=period,
            method="parkinson",
        )
    )

    working = frame[["high", "low"]].dropna()
    hl_ratio = (working["high"] / working["low"]).map(math.log)
    hl_ratio_sq = hl_ratio.pow(2)
    rolling_sum = hl_ratio_sq.rolling(window=period, min_periods=period).sum()
    vol_series = (rolling_sum / (period * 4.0 * math.log(2.0))).pow(0.5).dropna()
    daily_vol = vol_series.iloc[-1]

    assert result["method"] == "parkinson"
    assert result["daily_vol"] == pytest.approx(round(daily_vol * 100.0, 2))
    assert result["regime"] in {
        "very_low",
        "low",
        "normal",
        "elevated",
        "high",
        "extreme",
    }


def test_historical_volatility_validates_inputs(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame.iloc[:2], metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError):
        run(
            volatility.historical_volatility(
                dummy_ctx,
                "HOOD",
                period=5,
                method="close_to_close",
            )
        )


def test_expected_move_fetches_atm_from_option_chain(monkeypatch, dummy_ctx):
    chain_payload = {
        "underlyingPrice": 100.0,
        "callExpDateMap": {
            "2024-11-15:28": {
                "100.0": [
                    {
                        "mark": 2.5,
                        "bid": 2.4,
                        "ask": 2.6,
                    }
                ],
                "105.0": [
                    {
                        "mark": 1.5,
                    }
                ],
            }
        },
        "putExpDateMap": {
            "2024-11-15:28": {
                "100.0": [
                    {
                        "mark": 2.0,
                        "bid": 1.9,
                        "ask": 2.1,
                    }
                ]
            }
        },
    }

    async def fake_call(func, *args, **kwargs):
        assert func is dummy_ctx.options.get_option_chain
        assert args == ("HOOD",)
        assert kwargs["include_underlying_quote"] is True
        return chain_payload

    async def fail_fetch(*args, **kwargs):  # pragma: no cover
        raise AssertionError("fetch_price_frame should not be invoked")

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    result = run_tool(volatility.expected_move(dummy_ctx, "HOOD"))

    assert result["call_price"] == pytest.approx(2.5)
    assert result["put_price"] == pytest.approx(2.0)
    assert result["expected_move"] == pytest.approx(4.5)
    assert result["underlying_price"] == pytest.approx(100.0)
    assert result["expected_move_percent"] == pytest.approx(0.045)
    assert result["multiplier"] == pytest.approx(0.85)
    assert result["adjusted_move"] == pytest.approx(4.5 * 0.85)
    assert result["adjusted_move_percent"] == pytest.approx(0.045 * 0.85)

    boundaries = result["boundaries"]
    assert boundaries["upper_1x"] == pytest.approx(100.0 + 4.5 * 0.85)
    assert boundaries["lower_1x"] == pytest.approx(100.0 - 4.5 * 0.85)
    assert boundaries["upper_2x"] == pytest.approx(100.0 + 2 * 4.5 * 0.85)
    assert boundaries["lower_2x"] == pytest.approx(100.0 - 2 * 4.5 * 0.85)

    assert result["interval"] == "1d"


def test_expected_move_falls_back_to_price_history(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    chain_payload = {
        "callExpDateMap": {
            "2024-11-22:35": {
                "15.0": [
                    {
                        "bid": 1.0,
                        "ask": 1.2,
                    }
                ]
            }
        },
        "putExpDateMap": {
            "2024-11-22:35": {
                "15.0": [
                    {
                        "last": 1.1,
                    }
                ]
            }
        },
    }

    async def fake_call(func, *args, **kwargs):
        return chain_payload

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    result = run_tool(volatility.expected_move(dummy_ctx, "HOOD"))

    assert result["underlying_price"] == pytest.approx(15.0)
    assert result["expected_move"] == pytest.approx(2.2)
    assert result["adjusted_move"] == pytest.approx(2.2 * 0.85)
    assert result["boundaries"]["upper_1x"] == pytest.approx(15.0 + 2.2 * 0.85)
    assert result["interval"] == metadata["interval"]


def test_expected_move_validates_prices(dummy_ctx):
    with pytest.raises(ValueError):
        run(
            volatility.expected_move(
                dummy_ctx,
                "HOOD",
                call_price=-1.0,
                put_price=1.0,
            )
        )


def test_expected_move_validates_multiplier(dummy_ctx):
    with pytest.raises(ValueError):
        run(
            volatility.expected_move(
                dummy_ctx,
                "HOOD",
                call_price=1.0,
                put_price=1.0,
                underlying_price=100.0,
                multiplier=0,
            )
        )


def test_expected_move_uses_provided_premiums(monkeypatch, dummy_ctx):
    async def fail_call(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("option chain should not be fetched")

    async def fail_fetch(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("price history should not be fetched")

    monkeypatch.setattr(volatility, "call", fail_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    result = run_tool(
        volatility.expected_move(
            dummy_ctx,
            "HOOD",
            call_price=1.5,
            put_price=1.2,
            underlying_price=100.0,
        )
    )

    assert result["expected_move"] == pytest.approx(2.7)
    assert result["adjusted_move"] == pytest.approx(2.7 * 0.85)
    assert result["expected_move_percent"] == pytest.approx(0.027)
    assert result["adjusted_move_percent"] == pytest.approx(0.027 * 0.85)
    assert result["interval"] == "1d"


def test_expected_move_honors_custom_multiplier(monkeypatch, dummy_ctx):
    async def fail_call(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("option chain should not be fetched")

    async def fail_fetch(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("price history should not be fetched")

    monkeypatch.setattr(volatility, "call", fail_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    result = run_tool(
        volatility.expected_move(
            dummy_ctx,
            "HOOD",
            call_price=2.0,
            put_price=2.0,
            underlying_price=100.0,
            multiplier=1.2,
        )
    )

    assert result["adjusted_move"] == pytest.approx(4.0 * 1.2)
    assert result["boundaries"]["upper_1x"] == pytest.approx(100.0 + 4.8)
