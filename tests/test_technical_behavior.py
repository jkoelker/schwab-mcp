from __future__ import annotations

import datetime

import httpx
import pytest
from conftest import make_ctx, run

from schwab_mcp.tools.technical import moving_average


def test_moving_average_normalizes_candles_and_returns_real_indicator_values() -> None:
    """Sort and coerce Schwab candles before real SMA/EMA calculation and output."""
    candles = [
        {
            "datetime": 1704326400000,
            "open": 9.25,
            "high": 15.25,
            "low": 9.0,
            "close": "15.00",
            "volume": 1300,
        },
        {
            "datetime": 1704067200000,
            "open": 9.5,
            "high": 10.5,
            "low": 9.0,
            "close": "10.00",
            "volume": 1000,
        },
        {
            "datetime": 1704499200000,
            "open": 14.0,
            "high": 20.5,
            "low": 13.75,
            "close": "20.00",
            "volume": 1500,
        },
        {
            "datetime": 1704240000000,
            "open": 11.75,
            "high": 12.0,
            "low": 8.75,
            "close": "9.00",
            "volume": 1200,
        },
        {
            "datetime": 1704153600000,
            "open": 10.25,
            "high": 12.5,
            "low": 10.0,
            "close": "12.00",
            "volume": 1100,
        },
        {
            "datetime": 1704412800000,
            "open": 15.25,
            "high": 16.0,
            "low": 13.5,
            "close": "14.00",
            "volume": 1400,
        },
    ]

    class PriceHistoryClient:
        """Fake only the external Schwab price-history endpoint."""

        def __init__(self) -> None:
            self.requests: list[tuple[str, datetime.datetime, datetime.datetime]] = []

        async def get_price_history_every_day(
            self,
            symbol: str,
            *,
            start_datetime: datetime.datetime,
            end_datetime: datetime.datetime,
        ) -> httpx.Response:
            self.requests.append((symbol, start_datetime, end_datetime))
            return httpx.Response(
                200,
                json={"symbol": symbol, "candles": candles},
                request=httpx.Request("GET", "https://api.schwabapi.com/marketdata/v1/pricehistory"),
            )

    client = PriceHistoryClient()
    ctx = make_ctx(client)
    start = "2024-01-01T00:00:00+00:00"
    end = "2024-01-06T00:00:00+00:00"

    result = run(
        moving_average.moving_average(
            ctx,
            "MSFT",
            length=3,
            start=start,
            end=end,
            points=10,
        )
    )

    assert isinstance(result, dict)
    assert result["symbol"] == "MSFT"
    assert result["interval"] == "1d"
    assert result["start"] == "2024-01-01T00:00:00+00:00"
    assert result["end"] == "2024-01-06T00:00:00+00:00"
    assert result["candles"] == 6
    assert result["length"] == 3

    # pandas-ta uses the initial three-close SMA to seed its EMA. The later
    # values below follow alpha=2/(3+1); the serializer rounds to six decimals.
    # Half a unit at that precision (0.5e-6) allows rounding only, with no
    # relative tolerance.
    expected = [
        ("2024-01-03T00:00:00+00:00", 31 / 3, 31 / 3),
        ("2024-01-04T00:00:00+00:00", 12, 38 / 3),
        ("2024-01-05T00:00:00+00:00", 38 / 3, 40 / 3),
        ("2024-01-06T00:00:00+00:00", 49 / 3, 50 / 3),
    ]
    values = result["values"]
    assert len(values) == 4  # The first two rows are SMA warm-up rows.
    assert [row["timestamp"] for row in values] == [row[0] for row in expected]
    assert all(set(row) == {"timestamp", "sma_3", "ema_3"} for row in values)

    for row, (_, sma, ema) in zip(values, expected, strict=True):
        assert row["sma_3"] == pytest.approx(sma, rel=0, abs=0.5e-6)
        assert row["ema_3"] == pytest.approx(ema, rel=0, abs=0.5e-6)

    limited = run(
        moving_average.moving_average(
            ctx,
            "MSFT",
            length=3,
            start=start,
            end=end,
            points=2,
        )
    )
    assert isinstance(limited, dict)
    assert limited["values"] == values[-2:]
    assert client.requests == [
        (
            "MSFT",
            datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2024, 1, 6, tzinfo=datetime.timezone.utc),
        ),
        (
            "MSFT",
            datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2024, 1, 6, tzinfo=datetime.timezone.utc),
        ),
    ]
