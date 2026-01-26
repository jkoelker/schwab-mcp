import datetime
from enum import Enum
from types import SimpleNamespace

import pytest

from schwab_mcp.tools import history

from conftest import make_ctx, run


class DummyHistoryClient:
    PriceHistory = SimpleNamespace(
        PeriodType=Enum("PeriodType", "DAY MONTH YEAR YEAR_TO_DATE"),
        Period=Enum("Period", ["TEN_DAYS", "ONE_MONTH"]),
        FrequencyType=Enum("FrequencyType", "MINUTE DAILY WEEKLY MONTHLY"),
    )

    async def get_price_history(self, *args, **kwargs):
        return None

    async def get_price_history_every_minute(self, *args, **kwargs):
        return None

    async def get_price_history_every_five_minutes(self, *args, **kwargs):
        return None

    async def get_price_history_every_ten_minutes(self, *args, **kwargs):
        return None

    async def get_price_history_every_fifteen_minutes(self, *args, **kwargs):
        return None

    async def get_price_history_every_thirty_minutes(self, *args, **kwargs):
        return None

    async def get_price_history_every_day(self, *args, **kwargs):
        return None

    async def get_price_history_every_week(self, *args, **kwargs):
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


def test_get_price_history_every_minute_passes_flags(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    ctx = make_ctx(client)
    result = run(
        history.get_price_history_every_minute(
            ctx,
            "MSFT",
            start_datetime="2024-02-02T09:30:00",
            end_datetime="2024-02-02T09:35:00",
            extended_hours=False,
            previous_close=True,
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_price_history_every_minute

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("MSFT",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["start_datetime"] == datetime.datetime(2024, 2, 2, 9, 30)
    assert kwargs["end_datetime"] == datetime.datetime(2024, 2, 2, 9, 35)
    assert kwargs["need_extended_hours_data"] is False
    assert kwargs["need_previous_close"] is True


class TestSimplePriceHistoryFunctions:
    @pytest.fixture
    def client(self):
        return DummyHistoryClient()

    @pytest.fixture
    def ctx(self, client):
        return make_ctx(client)

    @pytest.mark.parametrize(
        ("func", "client_method"),
        [
            (
                history.get_price_history_every_five_minutes,
                "get_price_history_every_five_minutes",
            ),
            (
                history.get_price_history_every_ten_minutes,
                "get_price_history_every_ten_minutes",
            ),
            (
                history.get_price_history_every_fifteen_minutes,
                "get_price_history_every_fifteen_minutes",
            ),
            (
                history.get_price_history_every_thirty_minutes,
                "get_price_history_every_thirty_minutes",
            ),
            (history.get_price_history_every_day, "get_price_history_every_day"),
            (history.get_price_history_every_week, "get_price_history_every_week"),
        ],
    )
    def test_calls_correct_client_method(
        self, monkeypatch, ctx, client, func, client_method, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value={"candles": []})

        monkeypatch.setattr(history, "call", fake_call)

        result = run(func(ctx, "AAPL"))

        assert result == {"candles": []}
        assert captured["func"].__name__ == client_method
        assert captured["args"] == ("AAPL",)

    @pytest.mark.parametrize(
        "func",
        [
            history.get_price_history_every_five_minutes,
            history.get_price_history_every_ten_minutes,
            history.get_price_history_every_fifteen_minutes,
            history.get_price_history_every_thirty_minutes,
            history.get_price_history_every_day,
            history.get_price_history_every_week,
        ],
    )
    def test_parses_iso_datetimes(
        self, monkeypatch, ctx, client, func, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value={})

        monkeypatch.setattr(history, "call", fake_call)

        run(
            func(
                ctx,
                "SPY",
                start_datetime="2024-03-01T09:30:00",
                end_datetime="2024-03-01T16:00:00",
            )
        )

        assert captured["kwargs"]["start_datetime"] == datetime.datetime(
            2024, 3, 1, 9, 30, 0
        )
        assert captured["kwargs"]["end_datetime"] == datetime.datetime(
            2024, 3, 1, 16, 0, 0
        )

    @pytest.mark.parametrize(
        "func",
        [
            history.get_price_history_every_five_minutes,
            history.get_price_history_every_ten_minutes,
            history.get_price_history_every_fifteen_minutes,
            history.get_price_history_every_thirty_minutes,
            history.get_price_history_every_day,
            history.get_price_history_every_week,
        ],
    )
    def test_passes_extended_hours_and_previous_close(
        self, monkeypatch, ctx, client, func, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value={})

        monkeypatch.setattr(history, "call", fake_call)

        run(func(ctx, "SPY", extended_hours=True, previous_close=False))

        assert captured["kwargs"]["need_extended_hours_data"] is True
        assert captured["kwargs"]["need_previous_close"] is False
