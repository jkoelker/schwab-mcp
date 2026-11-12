"""The approval summary is rendered from the stored order spec, not tool arguments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from enum import Enum
from typing import Any, cast

import pytest
from conftest import make_ctx, run

from schwab_mcp.approvals.discord import DiscordApprovalManager
from schwab_mcp.approvals.signal import _BODY_LIMIT, SignalApprovalManager, SignalApprovalSettings
from schwab_mcp.context import SchwabContext
from schwab_mcp.previews import PreviewEntry, PreviewOperation
from schwab_mcp.tools import orders

ACCOUNT = "A" * 64


class SummaryClient:
    """Fake Schwab client covering the preview flow's surface."""

    class Instrument:
        Projection = Enum("Projection", {"SYMBOL_SEARCH": "symbol-search"})

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_instruments(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("get_instruments")
        return {}

    async def preview_order(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("preview_order")
        return {}


@pytest.fixture
def fake_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    monkeypatch.setattr(orders, "call", call)


def _stored_entry(
    ctx: SchwabContext,
    result: Any,
    operation: PreviewOperation = PreviewOperation.PLACE_ORDER,
) -> PreviewEntry:
    return ctx.previews.pop(result["preview_id"], ACCOUNT, operation=operation)


_OCO_FIRST = {"symbol": "AAPL", "quantity": 1, "instruction": "BUY", "order_type": "LIMIT", "price": 1.00}
_OCO_SECOND = {"symbol": "TSLA", "quantity": 5000, "instruction": "SELL", "order_type": "MARKET"}


def test_oco_summary_shows_second_leg(fake_call: None) -> None:
    """The second OCO leg is visible to the reviewer."""
    ctx = make_ctx(SummaryClient())

    result = run(
        orders.preview_oco_order(
            ctx,
            ACCOUNT,
            cast(orders._OrderDescInput, _OCO_FIRST),
            cast(orders._OrderDescInput, _OCO_SECOND),
        )
    )

    summary = _stored_entry(ctx, result).summary
    for token in ("SELL", "5000", "TSLA", "MARKET"):
        assert token in summary


_FOUR_LEG_COMBO = [
    {"symbol": "SPY   261218C00500000", "quantity": 10, "instruction": "BUY_TO_OPEN"},
    {"symbol": "SPY   261218C00510000", "quantity": 10, "instruction": "SELL_TO_OPEN"},
    {"symbol": "SPY   261218P00450000", "quantity": 10, "instruction": "SELL_TO_OPEN"},
    {"symbol": "SPY   261218P00440000", "quantity": 10, "instruction": "BUY_TO_OPEN"},
]

_PREVIEWS: dict[str, Callable[[SchwabContext], Awaitable[Any]]] = {
    "equity": lambda ctx: orders.preview_equity_order(
        ctx, ACCOUNT, "AAPL", 10, "BUY", "STOP_LIMIT", price=150.25, stop_price=149.5, session="AM", duration="GTC"
    ),
    "option": lambda ctx: orders.preview_option_order(
        ctx, ACCOUNT, "SPY   261218C00500000", 2, "BUY_TO_OPEN", "LIMIT", price=0.57, session="PM"
    ),
    "trailing_stop": lambda ctx: orders.preview_equity_trailing_stop_order(
        ctx, ACCOUNT, "AAPL", 50, "SELL", trail_offset=2.5, trail_type="PERCENT", duration="GTC"
    ),
    "oco": lambda ctx: orders.preview_oco_order(
        ctx,
        ACCOUNT,
        cast(orders._OrderDescInput, _OCO_FIRST),
        cast(orders._OrderDescInput, {**_OCO_SECOND, "session": "SEAMLESS"}),
    ),
    "trigger_one_exit": lambda ctx: orders.preview_trigger_order(
        ctx,
        ACCOUNT,
        cast(orders._OrderDescInput, {"symbol": "MSFT", "quantity": 7, "instruction": "BUY", "order_type": "MARKET"}),
        [
            cast(
                orders._OrderDescInput,
                {
                    "symbol": "MSFT",
                    "quantity": 7,
                    "instruction": "SELL",
                    "order_type": "STOP",
                    "stop_price": 380.0,
                    "duration": "GTC",
                },
            )
        ],
    ),
    "trigger_two_exits": lambda ctx: orders.preview_trigger_order(
        ctx,
        ACCOUNT,
        cast(
            orders._OrderDescInput,
            {"symbol": "MSFT", "quantity": 7, "instruction": "BUY", "order_type": "LIMIT", "price": 400.0},
        ),
        [
            cast(
                orders._OrderDescInput,
                {"symbol": "MSFT", "quantity": 7, "instruction": "SELL", "order_type": "LIMIT", "price": 440.0},
            ),
            cast(
                orders._OrderDescInput,
                {
                    "symbol": "MSFT",
                    "quantity": 7,
                    "instruction": "SELL",
                    "order_type": "TRAILING_STOP",
                    "trail_offset": 3.0,
                },
            ),
        ],
    ),
    "bracket": lambda ctx: orders.preview_bracket_order(
        ctx,
        ACCOUNT,
        "NVDA",
        25,
        "BUY",
        "LIMIT",
        profit_price=150.0,
        loss_price=120.0,
        loss_type="STOP_LIMIT",
        loss_limit_price=119.5,
        entry_price=130.25,
        exit_duration="GTC",
    ),
    "option_combo": lambda ctx: orders.preview_option_combo_order(
        ctx, ACCOUNT, list(_FOUR_LEG_COMBO), "NET_CREDIT", price=1.35, complex_order_strategy_type="IRON_CONDOR"
    ),
    "replacement": lambda ctx: orders.preview_replacement_order(
        ctx,
        ACCOUNT,
        "12345",
        cast(
            orders._OrderDescInput,
            {
                "symbol": "AAPL",
                "quantity": 3,
                "instruction": "SELL",
                "order_type": "STOP_LIMIT",
                "price": 10.5,
                "stop_price": 10.75,
                "session": "AM",
            },
        ),
    ),
}


def _spec_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("childOrderStrategies", []):
        yield from _spec_nodes(child)


def _expected_tokens(spec: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for node in _spec_nodes(spec):
        for leg in node.get("orderLegCollection", []):
            tokens += [leg["instruction"], str(leg["quantity"]), leg["instrument"]["symbol"]]
        for field in ("price", "stopPrice", "stopPriceOffset", "session", "duration", "orderType"):
            if field in node:
                tokens.append(str(node[field]))
    return tokens


@pytest.mark.parametrize("tool", sorted(_PREVIEWS))
def test_summary_shows_every_leg_price_and_setting(fake_call: None, tool: str) -> None:
    """Every leg, price, session and duration in the stored spec is in the summary."""
    ctx = make_ctx(SummaryClient())

    result = run(_PREVIEWS[tool](ctx))

    operation = PreviewOperation.REPLACE_ORDER if tool == "replacement" else PreviewOperation.PLACE_ORDER
    entry = _stored_entry(ctx, result, operation)
    assert entry.summary == orders._spec_summary(entry.order_spec)
    for token in _expected_tokens(entry.order_spec):
        assert token in entry.summary, f"{token!r} missing from {entry.summary!r}"


@pytest.mark.parametrize("tool", ["option_combo", "bracket", "trigger_two_exits"])
def test_large_summaries_fit_both_backends(fake_call: None, tool: str) -> None:
    """A four-leg combo and a full bracket render within the backends' limits."""
    ctx = make_ctx(SummaryClient())
    entry = _stored_entry(ctx, run(_PREVIEWS[tool](ctx)))
    arguments = {
        "original_tool": entry.tool_name,
        "order_summary": entry.summary,
        "preview_id": "0123456789abcdef",
        "account_hash": ACCOUNT,
    }

    DiscordApprovalManager._format_arguments(arguments)

    signal = SignalApprovalManager(
        SignalApprovalSettings(
            api_url="http://127.0.0.1:8080", account="+15555550100", approver_numbers=frozenset({"+1"})
        )
    )
    request = orders.ApprovalRequest(
        id="approval", tool_name="place_previewed_order", request_id="req", client_id=None, arguments=arguments
    )
    assert len(signal._render_body(request)) <= _BODY_LIMIT


def test_summary_renders_unknown_scalar_fields() -> None:
    """A spec field the renderer has no label for is still shown."""
    spec = orders._prepare_equity_order("AAPL", 1, "BUY", "MARKET")
    spec["specialInstruction"] = "ALL_OR_NONE"
    spec["orderLegCollection"][0]["positionEffect"] = "OPENING"

    summary = orders._spec_summary(spec)

    assert "specialInstruction=ALL_OR_NONE" in summary
    assert "positionEffect=OPENING" in summary


@pytest.mark.parametrize(
    "mutate",
    [
        lambda spec: spec.__setitem__("cancelTime", {"date": "2026-01-01"}),
        lambda spec: spec.__setitem__("session", "AM\nApproved: yes"),
        lambda spec: spec["orderLegCollection"][0]["instrument"].__setitem__("cusip", ["x"]),
        lambda spec: spec.__setitem__("orderLegCollection", "not-a-list"),
    ],
)
def test_summary_refuses_values_it_cannot_show(mutate: Callable[[dict[str, Any]], None]) -> None:
    """A nested or non-printable value fails closed instead of being hidden."""
    spec = orders._prepare_equity_order("AAPL", 1, "BUY", "MARKET")
    mutate(spec)

    with pytest.raises(ValueError, match="cannot be shown"):
        orders._spec_summary(spec)


def test_approval_request_carries_summary_of_placed_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """The approval request shows the summary of exactly the spec that is placed."""
    ctx = make_ctx(SummaryClient())
    spec = orders._prepare_oco_order(_OCO_FIRST, _OCO_SECOND)
    preview_id = ctx.previews.put(
        ACCOUNT, spec, "preview_oco_order", orders._spec_summary(spec), operation=PreviewOperation.PLACE_ORDER
    )
    seen: dict[str, Any] = {}

    async def approve(_ctx: Any, request: Any) -> Any:
        seen["summary"] = request.arguments["order_summary"]
        return orders.ApprovalDecision.DENIED

    monkeypatch.setattr(orders, "run_approval", approve)

    with pytest.raises(PermissionError):
        run(orders.place_previewed_order(ctx, ACCOUNT, preview_id))

    assert seen["summary"] == orders._spec_summary(spec)
    assert "TSLA" in seen["summary"]


@pytest.mark.parametrize(("price", "shown"), [(1.15, "1.15"), (19.99, "19.99"), (0.57, "0.5700")])
def test_summary_price_matches_spec_price(fake_call: None, price: float, shown: str) -> None:
    """The reviewer sees the same price string Schwab receives."""
    ctx = make_ctx(SummaryClient())

    entry = _stored_entry(ctx, run(orders.preview_equity_order(ctx, ACCOUNT, "AAPL", 1, "BUY", "LIMIT", price=price)))

    assert entry.order_spec["price"] == shown
    assert f"@ ${shown} " in entry.summary
