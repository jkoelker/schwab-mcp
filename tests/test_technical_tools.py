import math
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest
from conftest import run

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools.technical import (
    base,
    momentum,
    moving_average,
    overlays,
    trend,
    volatility,
)


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


def test_moving_average_returns_sma_and_ema(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        assert ctx is dummy_ctx
        assert symbol == "HOOD"
        assert kwargs["interval"] == "1d"
        return frame, metadata

    def fake_sma(series, *, length):
        return series.rolling(length, min_periods=1).mean()

    def fake_ema(series, *, length):
        return series.ewm(span=length, adjust=False).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(sma=fake_sma, ema=fake_ema),
    )

    result = run_tool(moving_average.moving_average(dummy_ctx, "HOOD", length=3, points=2))

    assert result["symbol"] == "HOOD"
    assert result["interval"] == "1d"
    assert result["candles"] == len(frame)
    assert result["length"] == 3

    values = result["values"]
    assert len(values) == 2
    expected_sma = frame["close"].rolling(3, min_periods=1).mean().tail(2).to_numpy()
    expected_ema = frame["close"].ewm(span=3, adjust=False).mean().tail(2).to_numpy()
    for row, sma_value, ema_value in zip(values, expected_sma, expected_ema):
        assert row["timestamp"].endswith("+00:00")
        assert row["sma_3"] == pytest.approx(float(sma_value))
        assert row["ema_3"] == pytest.approx(float(ema_value))


def test_moving_average_drops_rows_missing_either_series(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_sma(series, *, length):
        # Real warmup behavior: no value until `length` periods have passed.
        return series.rolling(length, min_periods=length).mean()

    def fake_ema(series, *, length):
        # EMA warms up immediately, unlike SMA above, so early rows would
        # otherwise contain ema_{length} with no sma_{length}.
        return series.ewm(span=length, adjust=False).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(sma=fake_sma, ema=fake_ema),
    )

    result = run_tool(moving_average.moving_average(dummy_ctx, "HOOD", length=3, points=10))

    values = result["values"]
    assert len(values) == len(frame) - 2  # first two rows lack sma_3
    for row in values:
        assert "sma_3" in row
        assert "ema_3" in row


def test_moving_average_defaults_to_default_points(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        assert kwargs["bars"] >= 0
        return frame, metadata

    def fake_sma(series, *, length):
        return series.rolling(length, min_periods=1).mean()

    def fake_ema(series, *, length):
        return series.ewm(span=length, adjust=False).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(sma=fake_sma, ema=fake_ema),
    )

    result = run_tool(moving_average.moving_average(dummy_ctx, "HOOD", length=5))

    values = result["values"]
    assert len(values) == base.DEFAULT_POINTS
    last_ema = frame["close"].ewm(span=5, adjust=False).mean().iloc[-1]
    assert values[-1]["ema_5"] == pytest.approx(float(last_ema))


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
                "STOCHk": pd.Series([40.0, 50.0, 60.0, 70.0, 80.0, 90.0], index=close.index),
                "STOCHd": pd.Series([35.0, 45.0, 55.0, 65.0, 75.0, 85.0], index=close.index),
            }
        )
        return values

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        momentum,
        "pandas_ta",
        SimpleNamespace(
            stoch=fake_stoch,
            rsi=momentum.pandas_ta.rsi if hasattr(momentum.pandas_ta, "rsi") else fake_stoch,
        ),
    )

    result = run_tool(momentum.stoch(dummy_ctx, "HOOD", k_length=5, d_length=3, smooth_k=3, points=3))

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
    # pandas_ta_classic has no pivot_points implementation (confirmed empty on
    # 0.3.59), so this indicator is computed directly rather than delegated —
    # no pandas_ta monkeypatch needed here, unlike the other overlay tools.
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="standard", lookback=1, points=2))

    values = result["values"]
    assert len(values) == 2
    assert {"timestamp", "PP", "R1", "S1", "R2", "S2", "R3", "S3"}.issubset(values[-1].keys())

    high = frame["high"].shift(1)
    low = frame["low"].shift(1)
    close = frame["close"].shift(1)
    expected_pp = ((high + low + close) / 3).dropna().tail(2).to_numpy()
    for row, expected in zip(values, expected_pp):
        assert row["PP"] == pytest.approx(float(expected))


def test_pivot_points_rejects_unknown_method(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="Unsupported pivot method"):
        run(overlays.pivot_points(dummy_ctx, "HOOD", method="bogus"))


def test_pivot_points_demark_requires_open_column(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data
    frame = frame.drop(columns=["open"])

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="requires an 'open' column"):
        run(overlays.pivot_points(dummy_ctx, "HOOD", method="demark"))


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

    result = run_tool(trend.macd(dummy_ctx, "HOOD", fast_length=5, slow_length=10, signal_length=3, points=3))

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
    assert result["weekly_vol"] == pytest.approx(round(daily_vol * math.sqrt(5) * 100.0, 2))
    assert result["annualized_vol"] == pytest.approx(round(daily_vol * math.sqrt(252) * 100.0, 2))
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


def test_moving_average_defaults_to_default_points_not_length(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    def fake_sma(series, *, length):
        return series.rolling(length, min_periods=1).mean()

    def fake_ema(series, *, length):
        return series.ewm(span=length, adjust=False).mean()

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        moving_average,
        "pandas_ta",
        SimpleNamespace(sma=fake_sma, ema=fake_ema),
    )

    result = run_tool(moving_average.moving_average(dummy_ctx, "HOOD", length=5))

    values = result["values"]
    assert len(values) == base.DEFAULT_POINTS
    last_value = frame["close"].rolling(5, min_periods=1).mean().iloc[-1]
    assert values[-1]["sma_5"] == pytest.approx(float(last_value))


def test_atr_defaults_to_default_points_not_length(monkeypatch, dummy_ctx, ohlcv_data):
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

    result = run_tool(trend.atr(dummy_ctx, "HOOD", length=5))

    values = result["values"]
    assert len(values) == base.DEFAULT_POINTS
    assert values[-1]["atr_5"] == pytest.approx(1.0 + len(frame) - 1)


def test_vwap_defaults_to_default_points_not_length(monkeypatch, dummy_ctx, ohlcv_data):
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

    result = run_tool(overlays.vwap(dummy_ctx, "HOOD", length=5))

    values = result["values"]
    assert len(values) == base.DEFAULT_POINTS
    assert values[-1]["vwap"] == pytest.approx(100.0 + len(frame) - 1)


def test_pivot_points_defaults_to_default_points_not_lookback(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="standard", lookback=1))

    values = result["values"]
    assert len(values) == base.DEFAULT_POINTS


# ---------------------------------------------------------------------------
# base.py — normalize_interval
# ---------------------------------------------------------------------------


def test_normalize_interval_rejects_unknown_interval():
    with pytest.raises(ValueError, match="Unsupported interval"):
        base.normalize_interval("2h")


def test_normalize_interval_accepts_valid_intervals():
    for iv in ("1m", "5m", "10m", "15m", "30m", "1d", "1w"):
        assert base.normalize_interval(iv) == iv


# ---------------------------------------------------------------------------
# base.py — series_to_json edge cases
# ---------------------------------------------------------------------------


def test_series_to_json_returns_empty_for_empty_series():
    assert base.series_to_json(pd.Series([], dtype=float)) == []


def test_series_to_json_returns_empty_after_dropna():
    s = pd.Series([float("nan")], index=pd.date_range("2024-01-01", periods=1, tz="UTC"))
    assert base.series_to_json(s) == []


def test_series_to_json_uses_series_name_when_no_value_key():
    index = pd.date_range("2024-01-01", periods=2, tz="UTC")
    s = pd.Series([1.0, 2.0], index=index, name="my_col")
    rows = base.series_to_json(s)
    assert rows[-1]["my_col"] == pytest.approx(2.0)


def test_series_to_json_uses_value_fallback_name_when_no_name():
    index = pd.date_range("2024-01-01", periods=2, tz="UTC")
    s = pd.Series([1.0, 2.0], index=index)  # name=None
    rows = base.series_to_json(s)
    assert "value" in rows[-1]


def test_series_to_json_with_limit_none_returns_all_rows():
    index = pd.date_range("2024-01-01", periods=5, tz="UTC")
    s = pd.Series(range(5, 10), index=index, dtype=float)
    rows = base.series_to_json(s, limit=None, value_key="v")
    assert len(rows) == 5


def test_series_to_json_non_datetime_index_is_normalized():
    # String index → converted via pd.to_datetime path (covers non-DatetimeIndex branch)
    index = pd.Index(["2024-01-01", "2024-01-02"])
    s = pd.Series([10.0, 20.0], index=index)
    rows = base.series_to_json(s, value_key="x")
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# base.py — frame_to_json edge cases
# ---------------------------------------------------------------------------


def test_frame_to_json_returns_empty_for_empty_frame():
    assert base.frame_to_json(pd.DataFrame()) == []


def test_frame_to_json_returns_empty_when_all_non_numeric():
    index = pd.date_range("2024-01-01", periods=2, tz="UTC")
    frame = pd.DataFrame({"col": ["a", "b"]}, index=index)
    assert base.frame_to_json(frame) == []


def test_frame_to_json_with_limit_none_returns_all_rows():
    index = pd.date_range("2024-01-01", periods=4, tz="UTC")
    frame = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0]}, index=index)
    rows = base.frame_to_json(frame, limit=None)
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# base.py — compute_series_indicator error branches
# ---------------------------------------------------------------------------


def test_compute_series_indicator_raises_on_empty_frame(monkeypatch, dummy_ctx):
    async def fake_fetch(ctx, symbol, **kwargs):
        meta = {
            "symbol": symbol,
            "interval": "1d",
            "start": None,
            "end": "2024-01-06T00:00:00+00:00",
            "bars_requested": None,
            "empty": True,
            "candles_returned": 0,
        }
        return pd.DataFrame(), meta

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="No price data"):
        run(
            base.compute_series_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: None,
                indicator_name="test",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
                value_key="v",
                required_columns=(),  # skip column check so empty-frame branch fires
            )
        )


def test_compute_series_indicator_raises_when_fn_returns_none(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(RuntimeError, match="returned no values"):
        run(
            base.compute_series_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: None,
                indicator_name="bad_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
                value_key="v",
            )
        )


def test_compute_series_indicator_raises_when_fn_returns_dataframe(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(TypeError, match="got DataFrame"):
        run(
            base.compute_series_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: pd.DataFrame({"a": f["close"]}),
                indicator_name="bad_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
                value_key="v",
            )
        )


def test_compute_series_indicator_raises_when_result_all_nan(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="Not enough price history"):
        run(
            base.compute_series_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: pd.Series([float("nan")] * len(f), index=f.index),
                indicator_name="all_nan_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
                value_key="v",
            )
        )


def test_compute_series_indicator_includes_extra_metadata(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run(
        base.compute_series_indicator(
            dummy_ctx,
            "HOOD",
            indicator_fn=lambda f: f["close"],
            indicator_name="close",
            interval="1d",
            start=None,
            end=None,
            bars=10,
            points=3,
            value_key="close",
            extra_metadata={"foo": "bar"},
        )
    )
    assert isinstance(result, dict)
    assert result["foo"] == "bar"


# ---------------------------------------------------------------------------
# base.py — compute_frame_indicator error branches
# ---------------------------------------------------------------------------


def test_compute_frame_indicator_raises_on_empty_frame(monkeypatch, dummy_ctx):
    async def fake_fetch(ctx, symbol, **kwargs):
        meta = {
            "symbol": symbol,
            "interval": "1d",
            "start": None,
            "end": "2024-01-06T00:00:00+00:00",
            "bars_requested": None,
            "empty": True,
            "candles_returned": 0,
        }
        return pd.DataFrame(), meta

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="No price data"):
        run(
            base.compute_frame_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: None,
                indicator_name="test",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
                required_columns=(),  # skip column check so empty-frame branch fires
            )
        )


def test_compute_frame_indicator_raises_when_fn_returns_none(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(RuntimeError, match="returned no values"):
        run(
            base.compute_frame_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: None,
                indicator_name="bad_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
            )
        )


def test_compute_frame_indicator_raises_when_fn_returns_series(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(TypeError, match="got Series"):
        run(
            base.compute_frame_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: f["close"],
                indicator_name="bad_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
            )
        )


def test_compute_frame_indicator_raises_when_result_all_nan(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="Not enough price history"):
        run(
            base.compute_frame_indicator(
                dummy_ctx,
                "HOOD",
                indicator_fn=lambda f: pd.DataFrame({"a": [float("nan")] * len(f)}, index=f.index),
                indicator_name="all_nan_ind",
                interval="1d",
                start=None,
                end=None,
                bars=10,
                points=3,
            )
        )


def test_compute_frame_indicator_includes_extra_metadata(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run(
        base.compute_frame_indicator(
            dummy_ctx,
            "HOOD",
            indicator_fn=lambda f: pd.DataFrame({"a": f["close"]}, index=f.index),
            indicator_name="test",
            interval="1d",
            start=None,
            end=None,
            bars=10,
            points=3,
            extra_metadata={"baz": 42},
        )
    )
    assert isinstance(result, dict)
    assert result["baz"] == 42


# ---------------------------------------------------------------------------
# overlays.py — additional pivot methods
# ---------------------------------------------------------------------------


def test_pivot_points_fibonacci_returns_levels(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="fibonacci"))

    values = result["values"]
    assert len(values) > 0
    assert {"PP", "R1", "S1", "R2", "S2", "R3", "S3"}.issubset(values[-1].keys())


def test_pivot_points_camarilla_returns_r4_and_s4(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="camarilla"))

    values = result["values"]
    assert len(values) > 0
    assert {"PP", "R1", "S1", "R2", "S2", "R3", "S3", "R4", "S4"}.issubset(values[-1].keys())


def test_pivot_points_woodie_returns_levels(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="woodie"))

    values = result["values"]
    assert len(values) > 0
    assert {"PP", "R1", "S1", "R2", "S2"}.issubset(values[-1].keys())


def test_pivot_points_demark_with_open_column(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(base, "fetch_price_frame", fake_fetch)

    result = run_tool(overlays.pivot_points(dummy_ctx, "HOOD", method="demark"))

    values = result["values"]
    assert len(values) > 0
    assert {"PP", "R1", "S1"}.issubset(values[-1].keys())


def test_pivot_points_rejects_non_positive_lookback(dummy_ctx):
    with pytest.raises(ValueError, match="lookback must be positive"):
        run(overlays.pivot_points(dummy_ctx, "HOOD", lookback=0))


def test_vwap_rejects_non_positive_length(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(overlays, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="length must be positive"):
        run(overlays.vwap(dummy_ctx, "HOOD", length=0))


def test_vwap_raises_when_pandas_ta_returns_none(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(overlays, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(
            vwap=lambda *args, **kwargs: None,
            pivot_points=None,
            bbands=None,
        ),
    )

    with pytest.raises(RuntimeError, match="returned no values"):
        run(overlays.vwap(dummy_ctx, "HOOD"))


def test_vwap_raises_when_result_all_nan(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(overlays, "fetch_price_frame", fake_fetch)
    monkeypatch.setattr(
        overlays,
        "pandas_ta",
        SimpleNamespace(
            vwap=lambda high, low, close, volume, **kw: pd.Series([float("nan")] * len(close), index=close.index),
            pivot_points=None,
            bbands=None,
        ),
    )

    with pytest.raises(ValueError, match="Not enough price history"):
        run(overlays.vwap(dummy_ctx, "HOOD"))


def test_bollinger_bands_rejects_length_lte_one(dummy_ctx):
    with pytest.raises(ValueError, match="greater than 1"):
        run(overlays.bollinger_bands(dummy_ctx, "HOOD", length=1))


def test_bollinger_bands_rejects_non_positive_std_dev(dummy_ctx):
    with pytest.raises(ValueError, match="std_dev must be positive"):
        run(overlays.bollinger_bands(dummy_ctx, "HOOD", std_dev=0.0))


# ---------------------------------------------------------------------------
# trend.py — validation errors
# ---------------------------------------------------------------------------


def test_macd_rejects_non_positive_lengths(dummy_ctx):
    with pytest.raises(ValueError, match="must be positive"):
        run(trend.macd(dummy_ctx, "HOOD", fast_length=0, slow_length=26))


def test_macd_rejects_fast_gte_slow(dummy_ctx):
    with pytest.raises(ValueError, match="fast_length must be less"):
        run(trend.macd(dummy_ctx, "HOOD", fast_length=26, slow_length=12))


def test_atr_rejects_non_positive_length(dummy_ctx):
    with pytest.raises(ValueError, match="length must be a positive integer"):
        run(trend.atr(dummy_ctx, "HOOD", length=0))


def test_adx_rejects_non_positive_length(dummy_ctx):
    with pytest.raises(ValueError, match="length must be a positive integer"):
        run(trend.adx(dummy_ctx, "HOOD", length=0))


# ---------------------------------------------------------------------------
# volatility.py — _volatility_regime branches
# ---------------------------------------------------------------------------


def test_volatility_regime_very_low():
    assert volatility._volatility_regime(5.0) == "very_low"


def test_volatility_regime_low():
    assert volatility._volatility_regime(12.0) == "low"


def test_volatility_regime_normal():
    assert volatility._volatility_regime(17.0) == "normal"


def test_volatility_regime_elevated():
    assert volatility._volatility_regime(25.0) == "elevated"


def test_volatility_regime_high():
    assert volatility._volatility_regime(40.0) == "high"


def test_volatility_regime_extreme():
    assert volatility._volatility_regime(60.0) == "extreme"


def test_compute_percentile_returns_50_for_empty_series():
    assert volatility._compute_percentile(pd.Series([], dtype=float), 0.1) == 50.0


# ---------------------------------------------------------------------------
# volatility.py — historical_volatility validation
# ---------------------------------------------------------------------------


def test_historical_volatility_rejects_period_lte_one(dummy_ctx):
    with pytest.raises(ValueError, match="period must be greater than 1"):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", period=1))


def test_historical_volatility_rejects_non_positive_annualize_factor(dummy_ctx):
    with pytest.raises(ValueError, match="annualize_factor must be positive"):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", annualize_factor=0))


def test_historical_volatility_rejects_invalid_method(dummy_ctx):
    with pytest.raises(ValueError, match="Invalid method"):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", method="bogus"))


def test_historical_volatility_raises_on_empty_frame(monkeypatch, dummy_ctx):
    async def fake_fetch(ctx, symbol, **kwargs):
        meta = {
            "symbol": symbol,
            "interval": "1d",
            "start": None,
            "end": "2024-01-01T00:00:00+00:00",
            "bars_requested": None,
            "empty": True,
            "candles_returned": 0,
        }
        return pd.DataFrame(), meta

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="no data"):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", period=5))


def test_historical_volatility_parkinson_raises_on_insufficient_data(monkeypatch, dummy_ctx, ohlcv_data):
    frame, metadata = ohlcv_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame.iloc[:1], metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="Not enough high/low"):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", period=3, method="parkinson"))


def test_historical_volatility_log_returns_method(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        return frame, metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    result = run_tool(volatility.historical_volatility(dummy_ctx, "HOOD", period=3, method="log_returns"))

    assert result["method"] == "log_returns"
    assert result["daily_vol"] > 0
    assert result["annualized_vol"] > 0


def test_historical_volatility_close_to_close_raises_on_insufficient_returns(monkeypatch, dummy_ctx, price_data):
    frame, metadata = price_data

    async def fake_fetch(ctx, symbol, **kwargs):
        # Only 2 rows → 1 return value, not enough for period=3
        return frame.iloc[:2], metadata

    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError):
        run(volatility.historical_volatility(dummy_ctx, "HOOD", period=3, method="close_to_close"))


# ---------------------------------------------------------------------------
# volatility.py — expected_move error paths
# ---------------------------------------------------------------------------


def test_expected_move_raises_on_non_positive_put_price(dummy_ctx):
    with pytest.raises(ValueError, match="put_price must be a positive"):
        run(
            volatility.expected_move(
                dummy_ctx,
                "HOOD",
                call_price=1.0,
                put_price=-0.5,
                underlying_price=100.0,
            )
        )


def test_expected_move_raises_when_underlying_is_zero(monkeypatch, dummy_ctx):
    async def fake_fetch(ctx, symbol, **kwargs):
        index = pd.date_range("2024-01-01", periods=1, tz="UTC")
        frame = pd.DataFrame({"close": [0.0]}, index=index)
        meta = {
            "symbol": symbol,
            "interval": "1d",
            "start": None,
            "end": "2024-01-01T00:00:00+00:00",
            "bars_requested": None,
            "empty": False,
            "candles_returned": 1,
        }
        return frame, meta

    async def fake_call(func, *args, **kwargs):
        # Return chain with no underlyingPrice so underlying falls back to price history
        return {"callExpDateMap": {}, "putExpDateMap": {}}

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fake_fetch)

    with pytest.raises(ValueError, match="underlying_price must be positive"):
        run(volatility.expected_move(dummy_ctx, "HOOD"))


def test_expected_move_raises_when_no_atm_contracts(monkeypatch, dummy_ctx):
    async def fake_call(func, *args, **kwargs):
        return {
            "underlyingPrice": 100.0,
            "callExpDateMap": {},
            "putExpDateMap": {},
        }

    async def fail_fetch(*args, **kwargs):  # pragma: no cover
        raise AssertionError("should not fetch price history")

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    with pytest.raises(ValueError, match="Unable to locate at-the-money"):
        run(volatility.expected_move(dummy_ctx, "HOOD"))


def test_expected_move_raises_when_chain_response_bad_type(monkeypatch, dummy_ctx):
    async def fake_call(func, *args, **kwargs):
        return "not-a-mapping"

    monkeypatch.setattr(volatility, "call", fake_call)

    with pytest.raises(TypeError, match="Unexpected option chain response"):
        run(volatility.expected_move(dummy_ctx, "HOOD"))


def test_expected_move_selects_closer_strike_when_multiple(monkeypatch, dummy_ctx):
    """_select_atm_contracts picks the strike nearest the underlying price."""
    chain_payload = {
        "underlyingPrice": 100.0,
        "callExpDateMap": {
            "2024-11-15:28": {
                "99.0": [{"mark": 2.0}],
                "110.0": [{"mark": 0.5}],
            }
        },
        "putExpDateMap": {
            "2024-11-15:28": {
                "99.0": [{"mark": 1.8}],
                "110.0": [{"mark": 0.4}],
            }
        },
    }

    async def fake_call(func, *args, **kwargs):
        return chain_payload

    async def fail_fetch(*args, **kwargs):  # pragma: no cover
        raise AssertionError("should not fetch price history")

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    result = run_tool(volatility.expected_move(dummy_ctx, "HOOD"))

    # 99 is closer to 100 than 110, so mark=2.0 call and 1.8 put are selected
    assert result["call_price"] == pytest.approx(2.0)
    assert result["put_price"] == pytest.approx(1.8)


def test_option_price_falls_back_to_last_price():
    """_option_price uses last/lastPrice/closePrice when mark/bid+ask absent."""
    contract = {"last": 1.75}
    assert volatility._option_price(contract) == pytest.approx(1.75)


def test_option_price_raises_when_no_price_available():
    with pytest.raises(ValueError, match="missing price information"):
        volatility._option_price({})


def test_is_positive_number_returns_false_for_bad_value():
    assert volatility._is_positive_number("not-a-number") is False
    assert volatility._is_positive_number(None) is False
    assert volatility._is_positive_number(-1.0) is False


def test_expected_move_raises_when_atm_strike_has_no_matching_put(monkeypatch, dummy_ctx):
    """Calls exist but no matching put for any expiry key → ValueError."""
    chain_payload = {
        "underlyingPrice": 100.0,
        "callExpDateMap": {
            "2024-11-15:28": {
                "100.0": [{"mark": 2.0}],
            }
        },
        "putExpDateMap": {},  # no expiry key at all
    }

    async def fake_call(func, *args, **kwargs):
        return chain_payload

    async def fail_fetch(*args, **kwargs):  # pragma: no cover
        raise AssertionError("should not fetch price history")

    monkeypatch.setattr(volatility, "call", fake_call)
    monkeypatch.setattr(volatility, "fetch_price_frame", fail_fetch)

    with pytest.raises(ValueError, match="Unable to locate at-the-money"):
        run(volatility.expected_move(dummy_ctx, "HOOD"))
