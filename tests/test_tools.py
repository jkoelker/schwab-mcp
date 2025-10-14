import asyncio
import datetime
from enum import Enum
from types import SimpleNamespace
from typing import Any, cast

from schwab.client import AsyncClient
from schwab_mcp.tools import tools
from schwab_mcp.context import SchwabServerContext


class DummyToolsClient:
    class MarketHours:
        Market = Enum("Market", "EQUITY OPTION BOND")

    class Movers:
        Index = Enum("Index", "DJI COMPX SPX")
        SortOrder = Enum(
            "SortOrder", "VOLUME TRADES PERCENT_CHANGE_UP PERCENT_CHANGE_DOWN"
        )
        Frequency = Enum("Frequency", "ZERO ONE FIVE TEN")

    class Instrument:
        Projection = Enum(
            "Projection",
            "SYMBOL_SEARCH SYMBOL_REGEX DESCRIPTION_SEARCH DESCRIPTION_REGEX FUNDAMENTAL SEARCH",
        )

    async def get_market_hours(self, *args, **kwargs):
        return None

    async def get_movers(self, *args, **kwargs):
        return None

    async def get_instruments(self, *args, **kwargs):
        return None


def run(coro):
    return asyncio.run(coro)


def make_ctx(client: Any) -> Any:
    lifespan_context = SchwabServerContext(client=cast(AsyncClient, client))
    request_context = SimpleNamespace(lifespan_context=lifespan_context)
    return SimpleNamespace(fastmcp=SimpleNamespace(), request_context=request_context)


def test_get_market_hours_handles_string_inputs(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(tools, "call", fake_call)

    client = DummyToolsClient()
    ctx = make_ctx(client)
    result = run(
        tools.get_market_hours(
            ctx,
            "equity, option",
            date="2024-03-01",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_market_hours

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == (
        [
            client.MarketHours.Market.EQUITY,
            client.MarketHours.Market.OPTION,
        ],
    )

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["date"] == datetime.date(2024, 3, 1)


def test_get_movers_maps_enums(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(tools, "call", fake_call)

    client = DummyToolsClient()
    ctx = make_ctx(client)
    result = run(
        tools.get_movers(
            ctx,
            "spx",
            sort="percent_change_up",
            frequency="five",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_movers

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == (client.Movers.Index.SPX,)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["sort_order"] is client.Movers.SortOrder.PERCENT_CHANGE_UP
    assert kwargs["frequency"] is client.Movers.Frequency.FIVE


def test_get_instruments_supports_aliases(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(tools, "call", fake_call)

    client = DummyToolsClient()
    ctx = make_ctx(client)
    result = run(
        tools.get_instruments(
            ctx,
            "AAPL",
            projection="symbol-search",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_instruments

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("AAPL",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["projection"] is client.Instrument.Projection.SYMBOL_SEARCH
