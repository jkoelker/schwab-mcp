from __future__ import annotations

from enum import Enum
from typing import Any

import httpx
import pytest
from conftest import make_ctx, run
from typing_extensions import NotRequired, TypedDict

from schwab_mcp.tools import orders


class NestedOrdersClient:
    class Instrument:
        Projection = Enum("Projection", {"SYMBOL_SEARCH": "symbol-search"})

    def __init__(self) -> None:
        self.previews: list[dict[str, Any]] = []
        self.lookups: list[str] = []

    async def get_instruments(self, symbol: str, **kwargs: Any) -> httpx.Response:
        self.lookups.append(symbol)
        return httpx.Response(
            200,
            json={"instruments": [{"symbol": symbol, "assetType": "EQUITY"}]},
            request=httpx.Request("GET", "https://example.test/instruments"),
        )

    async def preview_order(self, account_hash: str, order_spec: dict[str, Any]) -> httpx.Response:
        self.previews.append(order_spec)
        return httpx.Response(
            200,
            json={"orderValidationResult": {"type": "ACCEPTED"}},
            request=httpx.Request("POST", "https://example.test/preview"),
        )

    async def place_order(self, account_hash: str, order_spec: dict[str, Any]) -> httpx.Response:
        raise AssertionError("A preview workflow must not place an order")


class OrderDescription(TypedDict):
    symbol: str
    quantity: int
    instruction: str
    order_type: str
    price: NotRequired[float]
    stop_price: NotRequired[float]
    trail_offset: NotRequired[float]
    trail_type: NotRequired[str]
    asset_type: NotRequired[str]
    session: NotRequired[str]
    duration: NotRequired[str]


def _leg(
    symbol: str,
    quantity: int,
    instruction: str,
    order_type: str,
    *,
    price: float | None = None,
    stop_price: float | None = None,
    session: str | None = None,
    duration: str | None = None,
) -> OrderDescription:
    leg: OrderDescription = {
        "symbol": symbol,
        "quantity": quantity,
        "instruction": instruction,
        "order_type": order_type,
    }
    if price is not None:
        leg["price"] = price
    if stop_price is not None:
        leg["stop_price"] = stop_price
    if session is not None:
        leg["session"] = session
    if duration is not None:
        leg["duration"] = duration
    return leg


@pytest.mark.parametrize(
    ("entry_instruction", "exit_instruction"),
    [("BUY", "SELL"), ("SELL", "BUY")],
)
@pytest.mark.parametrize(
    (
        "profit_price",
        "loss_price",
        "loss_type",
        "loss_limit_price",
        "child_strategy",
        "exit_session",
        "exit_duration",
        "expected_exit_session",
        "expected_exit_duration",
    ),
    [
        (125.0, None, "STOP", None, "SINGLE", None, None, "AM", "GOOD_TILL_CANCEL"),
        (None, 90.0, "STOP", None, "SINGLE", "PM", None, "PM", "GOOD_TILL_CANCEL"),
        (125.0, 90.0, "STOP_LIMIT", 89.0, "OCO", "PM", "IOC", "PM", "IMMEDIATE_OR_CANCEL"),
    ],
)
def test_bracket_preview_submits_nested_exit_structure(
    entry_instruction: str,
    exit_instruction: str,
    profit_price: float | None,
    loss_price: float | None,
    loss_type: str,
    loss_limit_price: float | None,
    child_strategy: str,
    exit_session: str | None,
    exit_duration: str | None,
    expected_exit_session: str,
    expected_exit_duration: str,
) -> None:
    client = NestedOrdersClient()
    ctx = make_ctx(client)
    result = run(
        orders.preview_bracket_order(
            ctx,
            "acct",
            "MSFT",
            3,
            entry_instruction,
            "STOP_LIMIT",
            profit_price=profit_price,
            loss_price=loss_price,
            loss_type=loss_type,
            loss_limit_price=loss_limit_price,
            entry_price=101.0,
            entry_stop_price=102.0,
            session="AM",
            duration="GTC",
            exit_session=exit_session,
            exit_duration=exit_duration,
        )
    )
    spec = client.previews[0]
    assert spec["orderStrategyType"] == "TRIGGER"
    assert "orderLegCollection" in spec
    entry_leg = spec["orderLegCollection"][0]
    assert entry_leg["instruction"] == entry_instruction
    assert entry_leg["quantity"] == 3
    assert entry_leg["instrument"]["symbol"] == "MSFT"
    assert spec["orderType"] == "STOP_LIMIT"
    assert spec["price"] == "101.00" and spec["stopPrice"] == "102.00"
    assert spec["session"] == "AM" and spec["duration"] == "GOOD_TILL_CANCEL"
    assert len(spec["childOrderStrategies"]) == 1
    exit_branch = spec["childOrderStrategies"][0]
    assert exit_branch["orderStrategyType"] == child_strategy
    exits = exit_branch["childOrderStrategies"] if child_strategy == "OCO" else [exit_branch]
    assert len(exits) == (2 if child_strategy == "OCO" else 1)
    assert all(leg["orderStrategyType"] == "SINGLE" for leg in exits)
    assert all(leg["session"] == expected_exit_session and leg["duration"] == expected_exit_duration for leg in exits)
    for leg in exits:
        item = leg["orderLegCollection"][0]
        assert item["instruction"] == exit_instruction
        assert item["quantity"] == 3
        assert item["instrument"]["symbol"] == "MSFT"
    if profit_price is not None:
        profit = next(leg for leg in exits if leg["orderType"] == "LIMIT")
        assert profit["price"] == "125.00"
    if loss_price is not None:
        loss_order_type = "STOP_LIMIT" if loss_type == "STOP_LIMIT" else "STOP"
        loss = next(leg for leg in exits if leg["orderType"] == loss_order_type)
        assert loss["stopPrice"] == "90.00"
        if loss_type == "STOP_LIMIT":
            assert loss["price"] == "89.00"
    assert len(exits) == int(profit_price is not None) + int(loss_price is not None)
    assert result["preview_id"]
    cached = ctx.previews.pop(result["preview_id"], "acct", operation=orders.PreviewOperation.PLACE_ORDER)
    assert cached.tool_name == "preview_bracket_order"
    assert cached.order_spec == spec
    assert set(client.lookups) == {"MSFT"}


@pytest.mark.parametrize("exit_count", [1, 2])
def test_trigger_preview_preserves_exit_legs_and_leg_overrides(exit_count: int) -> None:
    client = NestedOrdersClient()
    entry = _leg("MSFT", 3, "BUY", "LIMIT", price=100, session="AM", duration="GTC")
    exits = [
        _leg("MSFT", 3, "SELL", "STOP_LIMIT", stop_price=91, price=90, session="PM"),
        _leg("MSFT", 3, "SELL", "LIMIT", price=120, duration="IOC"),
    ][:exit_count]
    ctx = make_ctx(client)
    result = run(orders.preview_trigger_order(ctx, "acct", entry, exits, session="SEAMLESS", duration="DAY"))
    spec = client.previews[0]
    cached = ctx.previews.pop(result["preview_id"], "acct", operation=orders.PreviewOperation.PLACE_ORDER)
    assert cached.order_spec == spec
    assert spec["orderStrategyType"] == "TRIGGER"
    assert len(spec["childOrderStrategies"]) == 1
    entry_leg = spec["orderLegCollection"][0]
    assert entry_leg["instruction"] == "BUY" and entry_leg["quantity"] == 3
    assert entry_leg["instrument"]["symbol"] == "MSFT"
    assert spec["orderType"] == "LIMIT" and spec["price"] == "100.00"
    assert spec["session"] == "AM" and spec["duration"] == "GOOD_TILL_CANCEL"
    exit_branch = spec["childOrderStrategies"][0]
    if exit_count == 2:
        assert exit_branch["orderStrategyType"] == "OCO"
        actual_exits = exit_branch["childOrderStrategies"]
    else:
        assert exit_branch["orderStrategyType"] == "SINGLE"
        actual_exits = [exit_branch]
    assert len(actual_exits) == exit_count
    assert all(leg["orderStrategyType"] == "SINGLE" for leg in actual_exits)
    assert [leg["orderType"] for leg in actual_exits] == ["STOP_LIMIT", "LIMIT"][:exit_count]
    stop_limit = actual_exits[0]
    stop_leg = stop_limit["orderLegCollection"][0]
    assert stop_leg["instruction"] == "SELL" and stop_leg["quantity"] == 3
    assert stop_leg["instrument"]["symbol"] == "MSFT"
    assert stop_limit["stopPrice"] == "91.00" and stop_limit["price"] == "90.00"
    assert stop_limit["session"] == "PM" and stop_limit["duration"] == "DAY"
    if exit_count == 2:
        limit_leg = actual_exits[1]["orderLegCollection"][0]
        assert limit_leg["instruction"] == "SELL" and limit_leg["quantity"] == 3
        assert limit_leg["instrument"]["symbol"] == "MSFT"
        assert actual_exits[1]["price"] == "120.00"
        assert actual_exits[1]["session"] == "SEAMLESS"
        assert actual_exits[1]["duration"] == "IMMEDIATE_OR_CANCEL"
    assert set(client.lookups) == {"MSFT"}


def test_trigger_preview_inherits_nondefault_settings_for_unspecified_legs() -> None:
    client = NestedOrdersClient()
    ctx = make_ctx(client)
    entry = _leg("MSFT", 3, "BUY", "MARKET")
    exits = [
        _leg("MSFT", 3, "SELL", "LIMIT", price=120),
        _leg("MSFT", 3, "SELL", "STOP", stop_price=90),
    ]

    result = run(orders.preview_trigger_order(ctx, "acct", entry, exits, session="PM", duration="GTC"))
    spec = client.previews[0]
    cached = ctx.previews.pop(result["preview_id"], "acct", operation=orders.PreviewOperation.PLACE_ORDER)

    assert cached.order_spec == spec
    assert spec["session"] == "PM" and spec["duration"] == "GOOD_TILL_CANCEL"
    assert spec["orderLegCollection"][0]["instruction"] == "BUY"
    assert len(spec["childOrderStrategies"]) == 1
    oco_branch = spec["childOrderStrategies"][0]
    assert oco_branch["orderStrategyType"] == "OCO"
    assert len(oco_branch["childOrderStrategies"]) == 2
    assert all(leg["session"] == "PM" for leg in oco_branch["childOrderStrategies"])
    assert all(leg["duration"] == "GOOD_TILL_CANCEL" for leg in oco_branch["childOrderStrategies"])
    assert set(client.lookups) == {"MSFT"}


@pytest.mark.parametrize("workflow", ["bracket", "trigger"])
def test_invalid_nested_preview_has_no_preview_or_cache_side_effects(workflow: str) -> None:
    client = NestedOrdersClient()
    ctx = make_ctx(client)
    with pytest.raises(ValueError):
        if workflow == "bracket":
            run(orders.preview_bracket_order(ctx, "acct", "MSFT", 3, "BUY", "MARKET"))
        else:
            run(orders.preview_trigger_order(ctx, "acct", _leg("MSFT", 3, "BUY", "MARKET"), []))
    assert client.previews == []
    assert client.lookups == []
    # PreviewStore has no public size accessor; inspect its documented backing
    # store narrowly to verify invalid input did not create a cache entry.
    assert ctx.previews._entries == {}
