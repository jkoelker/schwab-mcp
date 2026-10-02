import datetime
import inspect
from typing import Any

import httpx
import pytest
from conftest import make_ctx, run
from schwab.client import AsyncClient

from schwab_mcp.tools import options


@pytest.mark.parametrize(
    ("from_date", "to_date", "today", "expected"),
    (
        (
            None,
            None,
            datetime.date(2024, 12, 15),
            (datetime.date(2024, 12, 15), datetime.date(2025, 2, 13)),
        ),
        (
            datetime.date(2024, 12, 15),
            None,
            None,
            (datetime.date(2024, 12, 15), datetime.date(2025, 2, 13)),
        ),
        (
            None,
            datetime.date(2025, 1, 5),
            datetime.date(2025, 1, 10),
            (datetime.date(2025, 1, 5), datetime.date(2025, 1, 5)),
        ),
        (
            None,
            datetime.date(2025, 2, 2),
            datetime.date(2025, 1, 10),
            (datetime.date(2025, 1, 10), datetime.date(2025, 2, 2)),
        ),
        (
            datetime.date(2025, 1, 1),
            datetime.date(2025, 2, 1),
            None,
            (datetime.date(2025, 1, 1), datetime.date(2025, 2, 1)),
        ),
        (
            datetime.date(2025, 1, 2),
            datetime.date(2025, 1, 1),
            None,
            (datetime.date(2025, 1, 2), datetime.date(2025, 1, 2)),
        ),
    ),
)
def test_expiration_window_normalization(
    from_date: datetime.date | None,
    to_date: datetime.date | None,
    today: datetime.date | None,
    expected: tuple[datetime.date | None, datetime.date | None],
) -> None:
    assert options._normalize_expiration_window(from_date, to_date, today=today) == expected


class OptionChainClient:
    """Return one HTTP response from the external Schwab endpoint."""

    Options = AsyncClient.Options

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.captured: dict[str, Any] = {}

    async def get_option_chain(self, symbol: str, **kwargs: Any) -> httpx.Response:
        inspect.signature(AsyncClient.get_option_chain).bind(self, symbol, **kwargs)
        self.captured = {"args": (symbol,), "kwargs": kwargs}
        return self.response


@pytest.mark.parametrize("verbose", (False, True), ids=("compact", "verbose"))
def test_advanced_option_chain_normalizes_maps_and_shapes_response(verbose: bool) -> None:
    payload = {
        "symbol": "AAPL",
        "status": "SUCCESS",
        "underlyingPrice": 200.0,
        "callExpDateMap": {
            "2025-02-13:60": {
                "200.0": [
                    {
                        "putCall": "CALL",
                        "symbol": "AAPL_021325C200",
                        "description": "AAPL Feb 13 2025 200 Call",
                        "strike": 200.0,
                        "bid": 0.0,
                        "ask": 1.25,
                        "last": 0.0,
                        "mark": 0.63,
                        "bidSize": 0,
                        "askSize": 14,
                        "volume": 0,
                        "openInterest": 123,
                        "delta": 0.0,
                        "gamma": 0.02,
                        "theta": -0.01,
                        "vega": 0.05,
                        "rho": 0.0,
                        "impliedVolatility": 0.3,
                        "inTheMoney": False,
                        "expirationDate": "2025-02-13",
                        "daysToExpiration": 60,
                        "expirationType": "R",
                    }
                ]
            }
        },
        "putExpDateMap": {
            "2025-02-13:60": {
                "200.0": [
                    {
                        "putCall": "PUT",
                        "symbol": "AAPL_021325P200",
                        "description": "AAPL Feb 13 2025 200 Put",
                        "strike": 200.0,
                        "bid": 1.1,
                        "ask": 1.3,
                        "volume": 4,
                        "openInterest": 81,
                        "delta": -0.4,
                        "inTheMoney": False,
                        "expirationDate": "2025-02-13",
                        "daysToExpiration": 60,
                        "expirationType": "R",
                    }
                ]
            }
        },
    }
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "https://api.schwabapi.com/marketdata/v1/chains"),
    )
    client = OptionChainClient(response)
    ctx = make_ctx(client)

    result = run(
        options.get_advanced_option_chain(
            ctx,
            "AAPL",
            contract_type="PUT",
            strike_count=7,
            include_underlying_quote=True,
            strategy="VERTICAL",
            interval="5",
            strike=200.0,
            strike_range="NEAR_THE_MONEY",
            from_date=datetime.date(2024, 12, 15),
            exp_month="JANUARY",
            option_type="STANDARD",
            verbose=verbose,
        )
    )

    request = client.captured
    assert request["args"] == ("AAPL",)
    kwargs = request["kwargs"]
    assert kwargs["contract_type"] is AsyncClient.Options.ContractType.PUT
    assert kwargs["strike_count"] == 7
    assert kwargs["include_underlying_quote"] is True
    assert kwargs["strategy"] is AsyncClient.Options.Strategy.VERTICAL
    assert kwargs["interval"] == "5"
    assert kwargs["strike"] == 200.0
    assert kwargs["strike_range"] is AsyncClient.Options.StrikeRange.NEAR_THE_MONEY
    assert kwargs["from_date"] == datetime.date(2024, 12, 15)
    assert kwargs["to_date"] == datetime.date(2025, 2, 13)
    assert kwargs["exp_month"] is AsyncClient.Options.ExpirationMonth.JANUARY
    assert kwargs["option_type"] is AsyncClient.Options.Type.STANDARD

    assert result["symbol"] == "AAPL"
    assert result["underlyingPrice"] == 200.0
    for map_key, side in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
        contract = result[map_key]["2025-02-13:60"]["200.0"][0]
        assert contract["strike"] == 200.0
        assert contract["inTheMoney"] is False
        if side == "CALL":
            assert contract["bid"] == 0.0
            assert contract["volume"] == 0
        if verbose:
            assert contract["description"] == f"AAPL Feb 13 2025 200 {side.title()}"
        else:
            assert "description" not in contract
            assert "putCall" not in contract


def test_compact_pruning_mutates_payload_in_place_and_retains_falsy_values() -> None:
    payload = {
        "callExpDateMap": {
            "2025-02-13:60": {
                "200.0": [
                    {
                        "strike": 200.0,
                        "bid": 0.0,
                        "volume": 0,
                        "inTheMoney": False,
                        "description": "call details",
                    }
                ]
            }
        },
        "putExpDateMap": {
            "2025-02-13:60": {
                "200.0": [
                    {
                        "strike": 200.0,
                        "bid": 0.0,
                        "volume": 0,
                        "inTheMoney": False,
                        "description": "put details",
                    }
                ]
            }
        },
    }

    result = options._prune_option_chain(payload)

    assert result is payload
    assert isinstance(result, dict)
    assert result["callExpDateMap"]["2025-02-13:60"]["200.0"][0] == {
        "strike": 200.0,
        "bid": 0.0,
        "volume": 0,
        "inTheMoney": False,
    }
    assert result["putExpDateMap"]["2025-02-13:60"]["200.0"][0] == {
        "strike": 200.0,
        "bid": 0.0,
        "volume": 0,
        "inTheMoney": False,
    }
