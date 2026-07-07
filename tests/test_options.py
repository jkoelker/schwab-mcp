import datetime
from enum import Enum
from typing import Any

from schwab_mcp.tools import options

from conftest import make_ctx, run


class DummyOptionsClient:
    class Options:
        ContractType = Enum("ContractType", "CALL PUT ALL")
        Strategy = Enum("Strategy", "SINGLE ANALYTICAL VERTICAL")
        StrikeRange = Enum(
            "StrikeRange",
            "IN_THE_MONEY NEAR_THE_MONEY OUT_OF_THE_MONEY STRIKES_ABOVE_MARKET STRIKES_BELOW_MARKET STRIKES_NEAR_MARKET ALL",
        )
        ExpirationMonth = Enum("ExpirationMonth", "JAN FEB MAR")
        Type = Enum("Type", "STANDARD NON_STANDARD ALL")

    async def get_option_chain(self, *args, **kwargs):
        return None

    async def get_option_expiration_chain(self, *args, **kwargs):
        return None


def test_get_advanced_option_chain_parses_and_maps_parameters(
    monkeypatch, fake_call_factory
):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(
        options.get_advanced_option_chain(
            ctx,
            "SPY",
            contract_type="put",
            strike_count=10,
            include_quotes=True,
            strategy="vertical",
            interval="2",
            strike=420.0,
            strike_range="near_the_money",
            from_date="2024-05-01",
            to_date="2024-06-01",
            volatility=0.25,
            underlying_price=415.5,
            interest_rate=0.03,
            days_to_expiration=30,
            exp_month="jan",
            option_type="standard",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_option_chain

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("SPY",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["contract_type"] is client.Options.ContractType.PUT
    assert kwargs["strike_count"] == 10
    assert kwargs["include_underlying_quote"] is True
    assert kwargs["strategy"] is client.Options.Strategy.VERTICAL
    assert kwargs["interval"] == "2"
    assert kwargs["strike"] == 420.0
    assert kwargs["strike_range"] is client.Options.StrikeRange.NEAR_THE_MONEY
    assert kwargs["from_date"] == datetime.date(2024, 5, 1)
    assert kwargs["to_date"] == datetime.date(2024, 6, 1)
    assert kwargs["volatility"] == 0.25
    assert kwargs["underlying_price"] == 415.5
    assert kwargs["interest_rate"] == 0.03
    assert kwargs["days_to_expiration"] == 30
    assert kwargs["exp_month"] is client.Options.ExpirationMonth.JAN
    assert kwargs["option_type"] is client.Options.Type.STANDARD


# ---------------------------------------------------------------------------
# _prune_contract / _prune_option_chain helpers
# ---------------------------------------------------------------------------

_SAMPLE_CONTRACT = {
    "strike": 420.0,
    "bid": 1.5,
    "ask": 1.6,
    "last": 1.55,
    "mark": 1.55,
    "bidSize": 10,
    "askSize": 20,
    "volume": 500,
    "openInterest": 1000,
    "delta": -0.35,
    "gamma": 0.05,
    "theta": -0.02,
    "vega": 0.1,
    "rho": 0.01,
    "impliedVolatility": 0.25,
    "inTheMoney": False,
    "expirationDate": "2024-06-21",
    "daysToExpiration": 30,
    "expirationType": "R",
    # Extra fields that should be stripped
    "description": "SPY Jun 21 2024 420 Put",
    "exchangeName": "OPR",
    "settlementType": " ",
    "deliverableNote": "",
}


def test_prune_contract_keeps_compact_fields():
    pruned = options._prune_contract(_SAMPLE_CONTRACT)
    assert set(pruned.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert pruned["strike"] == 420.0
    assert pruned["delta"] == -0.35
    assert "description" not in pruned
    assert "exchangeName" not in pruned


def _make_chain_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": "SPY",
        "callExpDateMap": {
            "2024-06-21:30": {
                "420.0": [contract],
            }
        },
        "putExpDateMap": {
            "2024-06-21:30": {
                "420.0": [contract],
            }
        },
    }


def test_prune_option_chain_default_prunes_contracts(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_make_chain_payload(_SAMPLE_CONTRACT))
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_option_chain(ctx, "SPY"))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    put_contract = result["putExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert set(call_contract.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert set(put_contract.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert "description" not in call_contract


def test_prune_option_chain_verbose_returns_raw(monkeypatch, fake_call_factory):
    payload = _make_chain_payload(_SAMPLE_CONTRACT)
    _, fake_call = fake_call_factory(return_value=payload)
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_option_chain(ctx, "SPY", verbose=True))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert "description" in call_contract


def test_prune_option_chain_advanced_default_prunes(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_make_chain_payload(_SAMPLE_CONTRACT))
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_advanced_option_chain(ctx, "SPY"))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert set(call_contract.keys()) == options._COMPACT_CONTRACT_FIELDS


def test_prune_option_chain_advanced_verbose_returns_raw(
    monkeypatch, fake_call_factory
):
    payload = _make_chain_payload(_SAMPLE_CONTRACT)
    _, fake_call = fake_call_factory(return_value=payload)
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_advanced_option_chain(ctx, "SPY", verbose=True))

    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert "description" in call_contract


def test_prune_option_chain_non_dict_payload_passthrough():
    assert options._prune_option_chain("not a dict") == "not a dict"
    assert options._prune_option_chain(None) is None
    assert options._prune_option_chain([1, 2, 3]) == [1, 2, 3]


def test_prune_option_chain_missing_exp_maps_passthrough():
    payload = {"symbol": "SPY", "status": "SUCCESS"}
    result = options._prune_option_chain(payload)
    assert result == {"symbol": "SPY", "status": "SUCCESS"}


def test_prune_option_chain_malformed_exp_map_no_raise():
    payload = {
        "callExpDateMap": "oops",
        "putExpDateMap": {"2024-06-21:30": "not-a-dict"},
    }
    # Should not raise, return payload unchanged for bad shapes
    result = options._prune_option_chain(payload)
    assert result is payload
