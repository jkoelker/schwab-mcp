from enum import Enum

from schwab_mcp.tools import quotes
from schwab_mcp.tools.quotes import _normalize_option_symbol

from conftest import make_ctx, run


class DummyQuotesClient:
    class Quote:
        Fields = Enum("Fields", "QUOTE FUNDAMENTAL EXTENDED REFERENCE REGULAR")

    async def get_quotes(self, *args, **kwargs):
        return None


def test_get_quotes_parses_symbols_and_fields(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(quotes, "call", fake_call)

    client = DummyQuotesClient()
    ctx = make_ctx(client)
    result = run(
        quotes.get_quotes(
            ctx,
            "AAPL, msft",
            fields="quote, fundamental",
            indicative=False,
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_quotes

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == (["AAPL", "msft"],)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["fields"] == [
        client.Quote.Fields.QUOTE,
        client.Quote.Fields.FUNDAMENTAL,
    ]
    assert kwargs["indicative"] is False


def test_normalize_option_symbol_pads_root_and_strike():
    assert _normalize_option_symbol("SPX 260821P06550") == "SPX   260821P06550000"


def test_normalize_option_symbol_already_correct():
    assert _normalize_option_symbol("SPX   260821P06550000") == "SPX   260821P06550000"


def test_normalize_option_symbol_regular_stock():
    assert _normalize_option_symbol("AAPL") == "AAPL"


def test_normalize_option_symbol_short_strike():
    assert _normalize_option_symbol("SPY 260207C500") == "SPY   260207C00500000"


def test_get_quotes_normalizes_option_symbols(monkeypatch, fake_call_factory):
    captured, fake_call = fake_call_factory()
    monkeypatch.setattr(quotes, "call", fake_call)

    client = DummyQuotesClient()
    ctx = make_ctx(client)
    result = run(quotes.get_quotes(ctx, "SPX 260821P06550"))

    assert result == "ok"
    args = captured["args"]
    assert args == (["SPX   260821P06550000"],)
