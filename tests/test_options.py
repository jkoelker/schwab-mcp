import asyncio
import datetime
from enum import Enum
from types import SimpleNamespace
from typing import Any, cast

from mcp.server.fastmcp import Context
from schwab.client import AsyncClient
from schwab_mcp.tools import options
from schwab_mcp.context import SchwabContext, SchwabServerContext


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


def run(coro):
    return asyncio.run(coro)


def make_ctx(client: Any) -> SchwabContext:
    lifespan_context = SchwabServerContext(client=cast(AsyncClient, client))
    request_context = SimpleNamespace(lifespan_context=lifespan_context)
    return cast(SchwabContext, Context(request_context=cast(Any, request_context)))


def test_get_advanced_option_chain_parses_and_maps_parameters(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

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
