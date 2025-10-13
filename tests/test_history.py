import asyncio
import datetime
from enum import Enum
from types import SimpleNamespace
from typing import Any

from schwab_mcp.tools import history


class DummyHistoryClient:
    PriceHistory = SimpleNamespace(
        PeriodType=Enum("PeriodType", "DAY MONTH YEAR YEAR_TO_DATE"),
        Period=Enum("Period", ["TEN_DAYS", "ONE_MONTH"]),
        FrequencyType=Enum("FrequencyType", "MINUTE DAILY WEEKLY MONTHLY"),
    )

    async def get_advanced_price_history(self, *args, **kwargs):
        return None

    async def get_price_history_every_minute(self, *args, **kwargs):
        return None


def run(coro):
    return asyncio.run(coro)


def test_get_advanced_price_history_normalizes_inputs(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    result = run(
        history.get_advanced_price_history(
            client,
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
    assert captured["func"] == client.get_advanced_price_history

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


def test_get_price_history_every_minute_passes_flags(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(history, "call", fake_call)

    client = DummyHistoryClient()
    result = run(
        history.get_price_history_every_minute(
            client,
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
