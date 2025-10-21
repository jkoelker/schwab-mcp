import asyncio
from enum import Enum
from types import SimpleNamespace
from typing import Any, cast

from schwab.client import AsyncClient
from schwab_mcp.tools import quotes
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest


class DummyApprovalManager(ApprovalManager):
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED


class DummyQuotesClient:
    class Quote:
        Fields = Enum("Fields", "QUOTE FUNDAMENTAL EXTENDED REFERENCE REGULAR")

    async def get_quotes(self, *args, **kwargs):
        return None


def run(coro):
    return asyncio.run(coro)


def make_ctx(client: Any) -> SchwabContext:
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=DummyApprovalManager(),
    )
    request_context = SimpleNamespace(lifespan_context=lifespan_context)
    return SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )


def test_get_quotes_parses_symbols_and_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

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
