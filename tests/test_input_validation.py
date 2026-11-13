"""Model-supplied values are rejected before any Schwab client call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, cast

import pytest
from conftest import make_ctx, run

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools import account, orders, transactions

ACCOUNT = "A" * 64
GOOD_LEG: dict[str, Any] = {"symbol": "AAPL", "quantity": 1, "instruction": "BUY", "order_type": "MARKET"}
GOOD_COMBO = [
    {"symbol": "SPY   261218C00500000", "quantity": 1, "instruction": "BUY_TO_OPEN"},
    {"symbol": "SPY   261218C00510000", "quantity": 1, "instruction": "SELL_TO_OPEN"},
]


class RecordingClient:
    """Fake client that records every attribute call made through it."""

    class Instrument:
        Projection = Enum("Projection", {"SYMBOL_SEARCH": "symbol-search"})

    class Order:
        Status = Enum("Status", "WORKING FILLED")

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        async def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return {}

        return record


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> RecordingClient:
    async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    for module in (orders, account, transactions):
        monkeypatch.setattr(module, "call", call)
    return RecordingClient()


def _leg(**overrides: Any) -> orders._OrderDescInput:
    return cast(orders._OrderDescInput, {**GOOD_LEG, **overrides})


def _combo_leg(index: int, **overrides: Any) -> list[dict[str, Any]]:
    legs = [dict(leg) for leg in GOOD_COMBO]
    legs[index] = {**legs[index], **overrides}
    return legs


Call = Callable[[SchwabContext], Awaitable[Any]]

_BAD_SYMBOLS = ["AAPL\nfoo", "<@everyone>", "", "   ", "A" * 33, "AAPL‮", "AAPL_C"]
_BAD_QUANTITIES: list[Any] = [0, -1, True, 1.5]

_CASES: dict[str, Call] = {}
for _i, _symbol in enumerate(_BAD_SYMBOLS):
    _CASES[f"equity-symbol-{_i}"] = lambda ctx, s=_symbol: orders.preview_equity_order(
        ctx, ACCOUNT, s, 1, "BUY", "MARKET"
    )
for _i, _qty in enumerate(_BAD_QUANTITIES):
    _CASES[f"equity-quantity-{_i}"] = lambda ctx, q=_qty: orders.preview_equity_order(
        ctx, ACCOUNT, "AAPL", q, "BUY", "MARKET"
    )
_CASES.update(
    {
        "equity-instruction": lambda ctx: orders.preview_equity_order(ctx, ACCOUNT, "AAPL", 1, "HOLD", "MARKET"),
        "equity-session": lambda ctx: orders.preview_equity_order(
            ctx, ACCOUNT, "AAPL", 1, "BUY", "MARKET", session="AM\nApproved"
        ),
        "option-symbol": lambda ctx: orders.preview_option_order(
            ctx, ACCOUNT, "SPY\n251219C500", 1, "BUY_TO_OPEN", "MARKET"
        ),
        "option-quantity": lambda ctx: orders.preview_option_order(
            ctx, ACCOUNT, "SPY 251219C500", 0, "BUY_TO_OPEN", "MARKET"
        ),
        "option-instruction": lambda ctx: orders.preview_option_order(
            ctx, ACCOUNT, "SPY 251219C500", 1, "BUY", "MARKET"
        ),
        "trailing-symbol": lambda ctx: orders.preview_equity_trailing_stop_order(
            ctx, ACCOUNT, "<b>AAPL</b>", 1, "SELL", trail_offset=1.0
        ),
        "trailing-quantity": lambda ctx: orders.preview_equity_trailing_stop_order(
            ctx, ACCOUNT, "AAPL", -5, "SELL", trail_offset=1.0
        ),
        "trailing-instruction": lambda ctx: orders.preview_equity_trailing_stop_order(
            ctx, ACCOUNT, "AAPL", 1, "SELL_SHORT", trail_offset=1.0
        ),
        "trailing-offset-nan": lambda ctx: orders.preview_equity_trailing_stop_order(
            ctx, ACCOUNT, "AAPL", 1, "SELL", trail_offset=float("nan")
        ),
        "oco-symbol": lambda ctx: orders.preview_oco_order(ctx, ACCOUNT, _leg(), _leg(symbol="TSLA\nok")),
        "oco-quantity": lambda ctx: orders.preview_oco_order(ctx, ACCOUNT, _leg(quantity=0), _leg()),
        "oco-instruction": lambda ctx: orders.preview_oco_order(ctx, ACCOUNT, _leg(), _leg(instruction="BUY\n")),
        "trigger-symbol": lambda ctx: orders.preview_trigger_order(ctx, ACCOUNT, _leg(), [_leg(symbol="A;B")]),
        "trigger-quantity": lambda ctx: orders.preview_trigger_order(ctx, ACCOUNT, _leg(quantity=-1), [_leg()]),
        "bracket-symbol": lambda ctx: orders.preview_bracket_order(
            ctx, ACCOUNT, "AAPL\n", 1, "BUY", "MARKET", profit_price=200.0
        ),
        "bracket-quantity": lambda ctx: orders.preview_bracket_order(
            ctx, ACCOUNT, "AAPL", 0, "BUY", "MARKET", profit_price=200.0
        ),
        "bracket-instruction": lambda ctx: orders.preview_bracket_order(
            ctx, ACCOUNT, "AAPL", 1, "BUY_TO_OPEN", "MARKET", profit_price=200.0
        ),
        "combo-symbol": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, _combo_leg(1, symbol="SPY\n1"), "NET_DEBIT", price=1.0
        ),
        "combo-quantity": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, _combo_leg(0, quantity="1"), "NET_DEBIT", price=1.0
        ),
        "combo-instruction": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, _combo_leg(1, instruction="SELL"), "NET_DEBIT", price=1.0
        ),
        "combo-extra-key": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, _combo_leg(0, price=9.99), "NET_DEBIT", price=1.0
        ),
        "combo-missing-key": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, [{"symbol": "SPY 251219C500", "quantity": 1}, GOOD_COMBO[1]], "NET_DEBIT", price=1.0
        ),
        "combo-not-a-dict": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, cast(list[dict[str, Any]], ["SPY 251219C500", GOOD_COMBO[1]]), "NET_DEBIT", price=1.0
        ),
        "combo-order-type": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, list(GOOD_COMBO), "NET\nDEBIT", price=1.0
        ),
        "combo-complex-type": lambda ctx: orders.preview_option_combo_order(
            ctx, ACCOUNT, list(GOOD_COMBO), "NET_DEBIT", price=1.0, complex_order_strategy_type="IRON\nCONDOR"
        ),
        "replacement-symbol": lambda ctx: orders.preview_replacement_order(
            ctx, ACCOUNT, "123", _leg(symbol="AAPL\nfoo")
        ),
        "replacement-quantity": lambda ctx: orders.preview_replacement_order(ctx, ACCOUNT, "123", _leg(quantity=0)),
        "replacement-order-id": lambda ctx: orders.preview_replacement_order(ctx, ACCOUNT, "../x", _leg()),
        "get-order-order-id": lambda ctx: orders.get_order(ctx, ACCOUNT, "../x"),
        "get-order-account": lambda ctx: orders.get_order(ctx, "acct/../../x", "123"),
        "get-orders-account": lambda ctx: orders.get_orders(ctx, "acct?x=1"),
        "get-account-account": lambda ctx: account.get_account(ctx, "../accounts"),
        "get-transactions-account": lambda ctx: transactions.get_transactions(ctx, "acct#frag"),
        "get-transaction-account": lambda ctx: transactions.get_transaction(ctx, "acct/x", "1"),
        "get-transaction-id": lambda ctx: transactions.get_transaction(ctx, ACCOUNT, "1/../2"),
    }
)


def test_symbol_with_newline_is_rejected_before_any_call(client: RecordingClient) -> None:
    ctx = make_ctx(client)

    with pytest.raises(ValueError, match="symbol"):
        run(orders.preview_equity_order(ctx, ACCOUNT, "AAPL\nfoo", 1, "BUY", "MARKET"))

    assert client.calls == []


def test_get_order_rejects_path_traversal(client: RecordingClient) -> None:
    ctx = make_ctx(client)

    with pytest.raises(ValueError, match="order_id"):
        run(orders.get_order(ctx, ACCOUNT, "../x"))

    assert client.calls == []


@pytest.mark.parametrize("case", sorted(_CASES))
def test_rejected_before_any_client_call(client: RecordingClient, case: str) -> None:
    ctx = make_ctx(client)

    with pytest.raises(ValueError):
        run(_CASES[case](ctx))

    assert client.calls == []


@pytest.mark.parametrize(
    "symbol",
    ["AAPL", "BRK.B", "BRK/B", "$SPX", "/ES", "SPY   261218C00500000", "SPY 251219C500", "BF-B", "X"],
)
def test_real_symbol_forms_are_accepted(client: RecordingClient, symbol: str) -> None:
    ctx = make_ctx(client)

    run(orders.preview_equity_order(ctx, ACCOUNT, symbol, 1, "BUY", "MARKET"))

    assert "preview_order" in client.calls


def test_valid_reads_reach_the_client(client: RecordingClient) -> None:
    ctx = make_ctx(client)

    run(orders.get_order(ctx, ACCOUNT, "1234567890"))
    run(transactions.get_transaction(ctx, ACCOUNT, "98765"))

    assert client.calls == ["get_order", "get_transaction"]
