import datetime
import json
from enum import Enum
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import make_ctx, run
from schwab.client import AsyncClient

from schwab_mcp.tools import history
from schwab_mcp.tools.utils import SchwabAPIError


class DummyHistoryClient:
    PriceHistory = SimpleNamespace(
        PeriodType=Enum("PeriodType", "DAY MONTH YEAR YEAR_TO_DATE"),
        Period=Enum("Period", ["TEN_DAYS", "ONE_MONTH"]),
        FrequencyType=Enum("FrequencyType", "MINUTE DAILY WEEKLY MONTHLY"),
    )

    async def get_price_history(self, *args, **kwargs):
        return None


class HistoryResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
        url: str = "https://api.schwabapi.com/marketdata/v1/pricehistory",
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode()
        request = httpx.Request("GET", url)
        self._http_response = httpx.Response(
            status_code,
            request=request,
            content=self.content,
        )

    def raise_for_status(self) -> None:
        self._http_response.raise_for_status()

    def json(self) -> dict[str, Any]:
        return self.payload


class PriceHistoryEndpointFake:
    PriceHistory = AsyncClient.PriceHistory

    def __init__(self, response: HistoryResponse) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    async def get_price_history(self, symbol: str, **kwargs: Any) -> HistoryResponse:
        self.request = {"symbol": symbol, **kwargs}
        return self.response


def test_get_advanced_price_history_returns_candles_and_maps_sdk_request() -> None:
    payload = {
        "symbol": "SPY",
        "empty": False,
        "previousClose": 508.17,
        "candles": [
            {
                "open": 510.25,
                "high": 512.4,
                "low": 509.8,
                "close": 511.9,
                "volume": 2_731_849,
                "datetime": 1_709_315_400_000,
            }
        ],
    }
    client = PriceHistoryEndpointFake(HistoryResponse(payload))
    ctx = make_ctx(client)

    result = run(
        history.get_advanced_price_history(
            ctx,
            "SPY",
            period_type="dAy",
            period="tEn_DaYs",
            frequency_type="mInUtE",
            frequency="5",
            start_datetime="2024-03-01T09:30:00-05:00",
            end_datetime="2024-03-01T16:00:00-05:00",
            extended_hours=True,
            previous_close=False,
        )
    )

    assert result == payload
    assert client.request == {
        "symbol": "SPY",
        "period_type": AsyncClient.PriceHistory.PeriodType.DAY,
        "period": AsyncClient.PriceHistory.Period.TEN_DAYS,
        "frequency_type": AsyncClient.PriceHistory.FrequencyType.MINUTE,
        "frequency": 5,
        "start_datetime": datetime.datetime.fromisoformat("2024-03-01T09:30:00-05:00"),
        "end_datetime": datetime.datetime.fromisoformat("2024-03-01T16:00:00-05:00"),
        "need_extended_hours_data": True,
        "need_previous_close": False,
    }


def test_get_advanced_price_history_converts_failed_response_to_api_error() -> None:
    url = "https://api.schwabapi.com/marketdata/v1/pricehistory?symbol=SPY"
    response = HistoryResponse(
        {"error": "Invalid or expired token"},
        status_code=401,
        url=url,
    )
    client = PriceHistoryEndpointFake(response)
    ctx = make_ctx(client)

    with pytest.raises(SchwabAPIError) as error:
        run(history.get_advanced_price_history(ctx, "SPY", period_type="day"))

    message = str(error.value)
    assert "status=401" in message
    assert f"url={url}" in message
    assert response.text in message


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
