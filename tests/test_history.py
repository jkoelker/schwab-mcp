import datetime
from enum import Enum
from types import SimpleNamespace

from conftest import make_ctx, run

from schwab_mcp.tools import history


class DummyHistoryClient:
    PriceHistory = SimpleNamespace(
        PeriodType=Enum("PeriodType", "DAY MONTH YEAR YEAR_TO_DATE"),
        Period=Enum("Period", ["TEN_DAYS", "ONE_MONTH"]),
        FrequencyType=Enum("FrequencyType", "MINUTE DAILY WEEKLY MONTHLY"),
    )

    async def get_price_history(self, *args, **kwargs):
        return None


def test_get_advanced_price_history_normalizes_inputs(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    ctx = make_ctx(client)
    result = run(
        history.get_advanced_price_history(
            ctx,
            "SPY",
            period_type="day",
            period="ten_days",
            frequency_type="Minute",
            frequency="5",
            start_datetime="2024-01-01T09:30:00",
            end_datetime="2024-01-01T16:00:00",
            extended_hours=True,
            previous_close=False,
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_price_history

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("SPY",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["period_type"] is client.PriceHistory.PeriodType.DAY
    assert kwargs["period"] is client.PriceHistory.Period.TEN_DAYS
    assert kwargs["frequency_type"] is client.PriceHistory.FrequencyType.MINUTE
    assert kwargs["frequency"] == 5
    assert kwargs["need_extended_hours_data"] is True
    assert kwargs["need_previous_close"] is False
    assert kwargs["start_datetime"] == datetime.datetime(2024, 1, 1, 9, 30)
    assert kwargs["end_datetime"] == datetime.datetime(2024, 1, 1, 16, 0)


def test_get_advanced_price_history_no_params(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory(return_value={"candles": []})

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    ctx = make_ctx(client)
    result = run(history.get_advanced_price_history(ctx, "AAPL"))

    assert result == {"candles": []}
    assert captured["func"] == client.get_price_history
    assert captured["args"] == ("AAPL",)
    assert captured["kwargs"]["period_type"] is None
    assert captured["kwargs"]["period"] is None
    assert captured["kwargs"]["frequency_type"] is None
    assert captured["kwargs"]["frequency"] is None


def test_get_advanced_price_history_intraday(monkeypatch, fake_call_factory):
    """Verify intraday use: frequency_type=MINUTE with frequency 1/5/10/15/30."""
    captured, fake_call = fake_call_factory(return_value={})

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    ctx = make_ctx(client)

    for freq in [1, 5, 10, 15, 30]:
        run(
            history.get_advanced_price_history(
                ctx,
                "SPY",
                period_type="DAY",
                frequency_type="MINUTE",
                frequency=freq,
                start_datetime="2024-03-01T09:30:00",
                end_datetime="2024-03-01T16:00:00",
            )
        )
        assert captured["kwargs"]["frequency_type"] is client.PriceHistory.FrequencyType.MINUTE
        assert captured["kwargs"]["frequency"] == freq
