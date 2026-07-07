from enum import Enum

from schwab_mcp.tools import quotes

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


# ---------------------------------------------------------------------------
# _prune_quote / _prune_quotes helpers
# ---------------------------------------------------------------------------

_SAMPLE_RAW_QUOTE_ENTRY = {
    "assetMainType": "EQUITY",
    "symbol": "AAPL",
    "quoteType": "NBBO",
    "quote": {
        "lastPrice": 195.50,
        "bidPrice": 195.45,
        "askPrice": 195.55,
        "mark": 195.50,
        "netChange": 1.23,
        "netPercentChange": 0.63,
        "highPrice": 196.00,
        "lowPrice": 194.50,
        "totalVolume": 54321000,
        "bidSize": 100,
        "askSize": 200,
        "openPrice": 194.80,
    },
    "reference": {"cusip": "037833100", "exchange": "Q"},
    "fundamental": {"peRatio": 30.5, "eps": 6.43},
}

_SAMPLE_PAYLOAD = {"AAPL": _SAMPLE_RAW_QUOTE_ENTRY}


def test_prune_quotes_compact_default(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_SAMPLE_PAYLOAD)
    monkeypatch.setattr(quotes, "call", fake_call)

    client = DummyQuotesClient()
    ctx = make_ctx(client)
    result = run(quotes.get_quotes(ctx, "AAPL"))

    assert isinstance(result, dict)
    entry = result["AAPL"]
    assert entry["symbol"] == "AAPL"
    # Compact fields present
    assert entry["lastPrice"] == 195.50
    assert entry["bidPrice"] == 195.45
    assert entry["askPrice"] == 195.55
    assert entry["mark"] == 195.50
    assert entry["netChange"] == 1.23
    assert entry["netPercentChange"] == 0.63
    assert entry["highPrice"] == 196.00
    assert entry["lowPrice"] == 194.50
    assert entry["totalVolume"] == 54321000
    # Extra quote fields stripped
    assert "bidSize" not in entry
    assert "askSize" not in entry
    assert "openPrice" not in entry
    # Top-level blocks stripped
    assert "fundamental" not in entry
    assert "reference" not in entry
    assert "quoteType" not in entry


def test_prune_quotes_verbose_returns_raw(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_SAMPLE_PAYLOAD)
    monkeypatch.setattr(quotes, "call", fake_call)

    client = DummyQuotesClient()
    ctx = make_ctx(client)
    result = run(quotes.get_quotes(ctx, "AAPL", verbose=True))

    assert result is _SAMPLE_PAYLOAD
    assert result["AAPL"]["fundamental"] == {"peRatio": 30.5, "eps": 6.43}


def test_prune_quotes_non_dict_passthrough():
    assert quotes._prune_quotes("not a dict") == "not a dict"
    assert quotes._prune_quotes(None) is None
    assert quotes._prune_quotes([1, 2, 3]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Fix #1: _COMPACT_QUOTE_FIELDS is a tuple — stable iteration order
# ---------------------------------------------------------------------------


def test_compact_quote_fields_is_tuple():
    assert isinstance(quotes._COMPACT_QUOTE_FIELDS, tuple)


def test_compact_quote_fields_iteration_order_is_stable():
    """Iterating the tuple twice must yield the same order."""
    first = list(quotes._COMPACT_QUOTE_FIELDS)
    second = list(quotes._COMPACT_QUOTE_FIELDS)
    assert first == second


def test_prune_quote_output_key_order_is_stable():
    """Keys emitted by _prune_quote must follow _COMPACT_QUOTE_FIELDS order."""
    entry = {
        "symbol": "AAPL",
        "quote": {k: i for i, k in enumerate(quotes._COMPACT_QUOTE_FIELDS)},
    }
    result = quotes._prune_quote("AAPL", entry)
    pruned_keys = [k for k in result if k != "symbol"]
    assert pruned_keys == list(quotes._COMPACT_QUOTE_FIELDS)


def test_compact_quote_fields_membership_check_works():
    """'in' membership check must still work on a tuple."""
    assert "lastPrice" in quotes._COMPACT_QUOTE_FIELDS
    assert "bidSize" not in quotes._COMPACT_QUOTE_FIELDS
