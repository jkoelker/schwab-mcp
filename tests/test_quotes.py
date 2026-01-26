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
