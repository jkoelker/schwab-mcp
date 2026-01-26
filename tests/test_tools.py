import datetime
from enum import Enum

from schwab_mcp.tools import tools
from schwab_mcp.tools import options as options_tools

from conftest import make_ctx, run


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


def test_get_market_hours_handles_string_inputs(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

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


def test_get_movers_maps_enums(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

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


def test_get_instruments_supports_aliases(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

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


def test_get_datetime_returns_eastern_time(monkeypatch):
    class DummyDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is not None
            return cls(2024, 1, 15, 12, 30, 45, tzinfo=tz)

    monkeypatch.setattr(tools.datetime, "datetime", DummyDatetime)

    result = run(tools.get_datetime())

    assert result.startswith("2024-01-15T12:30:45")
    assert "-05:00" in result or "-04:00" in result
    assert result.endswith("EST") or result.endswith("EDT")
    assert "Eastern Time" not in result


def test_get_option_chain_defaults_date_window(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(options_tools, "call", fake_call)

    class DummyDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2025, 2, 1)

    monkeypatch.setattr(options_tools.datetime, "date", DummyDate)

    class DummyOptionsClient:
        def get_option_chain(self, *args, **kwargs):  # pragma: no cover - stub
            raise AssertionError("Schwab client should be invoked via call helper")

    client = DummyOptionsClient()
    ctx = make_ctx(client)

    result = run(options_tools.get_option_chain(ctx, "AAPL"))

    assert result == "ok"
    kwargs = captured["kwargs"]
    assert kwargs["from_date"] == DummyDate(2025, 2, 1)
    assert kwargs["to_date"] == DummyDate(2025, 2, 1) + datetime.timedelta(days=60)


def test_get_option_chain_extends_missing_to_date(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(options_tools, "call", fake_call)

    class DummyOptionsClient:
        def get_option_chain(self, *args, **kwargs):  # pragma: no cover - stub
            raise AssertionError("Schwab client should be invoked via call helper")

    client = DummyOptionsClient()
    ctx = make_ctx(client)

    start = datetime.date(2025, 3, 5)
    run(options_tools.get_option_chain(ctx, "AAPL", from_date=start))

    kwargs = captured["kwargs"]
    assert kwargs["from_date"] == start
    assert kwargs["to_date"] == start + datetime.timedelta(days=60)


def test_get_advanced_option_chain_defaults_date_window(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(options_tools, "call", fake_call)

    class DummyDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2025, 4, 10)

    monkeypatch.setattr(options_tools.datetime, "date", DummyDate)

    class DummyOptionsClient:
        def get_option_chain(self, *args, **kwargs):  # pragma: no cover - stub
            raise AssertionError("Schwab client should be invoked via call helper")

    client = DummyOptionsClient()
    ctx = make_ctx(client)

    run(options_tools.get_advanced_option_chain(ctx, "SPY"))

    kwargs = captured["kwargs"]
    assert kwargs["from_date"] == DummyDate(2025, 4, 10)
    assert kwargs["to_date"] == DummyDate(2025, 4, 10) + datetime.timedelta(days=60)
