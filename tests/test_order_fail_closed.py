"""Order inputs fail closed at the registered MCP boundary and in the builders."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, cast

import pytest
from conftest import make_ctx, run
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool
from pydantic import ValidationError

from schwab_mcp.previews import PreviewOperation
from schwab_mcp.tools import orders

ACCOUNT = "A" * 64
_LEG = {"symbol": "AAPL", "quantity": 1, "instruction": "SELL", "order_type": "LIMIT", "price": 200.0}
_STOP_LEG = {"symbol": "AAPL", "quantity": 1, "instruction": "SELL", "order_type": "STOP", "stop_price": 150.0}
_COMBO_LEGS = [
    {"symbol": "SPY   260116C00400000", "quantity": 1, "instruction": "BUY_TO_OPEN"},
    {"symbol": "SPY   260116C00410000", "quantity": 1, "instruction": "SELL_TO_OPEN"},
]


class PreviewClient:
    """Fake Schwab client covering the preview flow's surface."""

    class Instrument:
        Projection = Enum("Projection", {"SYMBOL_SEARCH": "symbol-search"})

    def __init__(self) -> None:
        self.previewed: list[dict[str, Any]] = []

    async def get_instruments(self, *args: Any, **kwargs: Any) -> Any:
        return {}

    async def preview_order(self, *args: Any, **kwargs: Any) -> Any:
        self.previewed.append(kwargs["order_spec"])
        return {}


@pytest.fixture
def fake_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    monkeypatch.setattr(orders, "call", call)


def _registered(name: str) -> Tool:
    server = MCPServer(name="fail-closed")
    orders.register(server, allow_write=True)
    tools = cast(list[Tool], getattr(server, "_tool_manager").list_tools())
    return next(tool for tool in tools if tool.name == name)


# B1: option combo order_type and price follow the documented contract.

_COMBO_ACCEPTED = [("NET_CREDIT", 1.25), ("NET_DEBIT", 1.25), ("NET_ZERO", None), ("MARKET", None)]
_COMBO_REJECTED = [
    ("NET_CREDIT", None),
    ("NET_DEBIT", None),
    ("NET_ZERO", 1.0),
    ("MARKET", 1.0),
    ("LIMIT", 1.0),
    ("LIMIT", None),
    ("STOP", 1.0),
    ("STOP_LIMIT", 1.0),
    ("TRAILING_STOP", None),
]


@pytest.mark.parametrize(("order_type", "price"), _COMBO_ACCEPTED)
def test_combo_accepts_documented_type_and_price(order_type: str, price: float | None) -> None:
    spec = orders._prepare_option_combo_order(_COMBO_LEGS, order_type, price)
    assert spec["orderType"] == order_type
    assert ("price" in spec) == (price is not None)


@pytest.mark.parametrize(("order_type", "price"), _COMBO_REJECTED)
def test_combo_rejects_contradictory_type_and_price(order_type: str, price: float | None) -> None:
    with pytest.raises(ValueError, match="order_type|price"):
        orders._prepare_option_combo_order(_COMBO_LEGS, order_type, price)


@pytest.mark.parametrize(("order_type", "price"), _COMBO_ACCEPTED)
def test_registered_combo_previews_documented_type_and_price(
    fake_call: None, order_type: str, price: float | None
) -> None:
    tool = _registered("preview_option_combo_order")
    arguments: dict[str, Any] = {"account_hash": ACCOUNT, "legs": _COMBO_LEGS, "order_type": order_type}
    if price is not None:
        arguments["price"] = price
    client = PreviewClient()
    ctx = make_ctx(client)
    result = run(tool.fn(ctx, **tool.fn_metadata.validate_arguments(arguments)))
    entry = ctx.previews.pop(result["preview_id"], ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    assert client.previewed == [entry.order_spec]
    assert entry.order_spec["orderType"] == order_type


@pytest.mark.parametrize(("order_type", "price"), _COMBO_REJECTED)
def test_registered_combo_rejects_before_preview(fake_call: None, order_type: str, price: float | None) -> None:
    tool = _registered("preview_option_combo_order")
    arguments: dict[str, Any] = {"account_hash": ACCOUNT, "legs": _COMBO_LEGS, "order_type": order_type}
    if price is not None:
        arguments["price"] = price
    client = PreviewClient()
    with pytest.raises(ValueError, match="order_type|price"):
        run(tool.fn(make_ctx(client), **tool.fn_metadata.validate_arguments(arguments)))
    assert client.previewed == []


# B2: unknown nested order keys are rejected, not silently dropped.


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("preview_oco_order", {"first_order": {**_LEG, "unreviewed_intent": "x"}, "second_order": _LEG}),
        ("preview_oco_order", {"first_order": _LEG, "second_order": {**_LEG, "unreviewed_intent": "x"}}),
        ("preview_trigger_order", {"entry_order": {**_LEG, "unreviewed_intent": "x"}, "exit_orders": [_LEG]}),
        ("preview_trigger_order", {"entry_order": _LEG, "exit_orders": [{**_LEG, "unreviewed_intent": "x"}]}),
        ("preview_replacement_order", {"order_id": "123", "replacement_order": {**_LEG, "unreviewed_intent": "x"}}),
    ],
)
def test_registered_tools_reject_unknown_nested_order_keys(tool_name: str, arguments: dict[str, Any]) -> None:
    tool = _registered(tool_name)
    with pytest.raises(ValidationError, match="unreviewed_intent"):
        tool.fn_metadata.validate_arguments({"account_hash": ACCOUNT, **arguments})


def test_registered_order_schema_is_closed() -> None:
    schema = _registered("preview_oco_order").parameters
    assert schema["$defs"]["_OrderDescInput"]["additionalProperties"] is False


def test_order_desc_rejects_unknown_keys_on_direct_calls() -> None:
    with pytest.raises(ValueError, match="unreviewed_intent"):
        orders._prepare_oco_order({**_LEG, "unreviewed_intent": "x"}, _LEG)


# B3: every order node's strategy type is shown, SINGLE included.


def _strategy_nodes(node: dict[str, Any]) -> list[str]:
    found = [node["orderStrategyType"]]
    for child in node.get("childOrderStrategies", []):
        found += _strategy_nodes(child)
    return found


@pytest.mark.parametrize(
    "spec",
    [
        orders._prepare_option_combo_order(_COMBO_LEGS, "NET_DEBIT", 1.25),
        orders._prepare_oco_order(_LEG, _STOP_LEG),
        orders._prepare_trigger_order({**_LEG, "instruction": "BUY"}, [_LEG]),
    ],
    ids=["combo", "oco", "trigger"],
)
def test_summary_shows_every_node_strategy(spec: dict[str, Any]) -> None:
    lines = orders._spec_summary(spec).splitlines()
    strategies = _strategy_nodes(spec)
    assert len(lines) >= len(strategies)
    node_lines = [line for line in lines if not line.lstrip().startswith("leg ")]
    assert len(node_lines) == len(strategies)
    for line, strategy in zip(node_lines, strategies, strict=True):
        assert strategy in line.rstrip(":").split(), (strategy, line)


def test_simple_order_summary_shows_single() -> None:
    summary = orders._spec_summary(
        {
            "orderStrategyType": "SINGLE",
            "orderType": "MARKET",
            "session": "NORMAL",
            "duration": "DAY",
            "orderLegCollection": [
                {"instruction": "BUY", "quantity": 1, "instrument": {"symbol": "AAPL", "assetType": "EQUITY"}}
            ],
        }
    )
    assert summary == "SINGLE BUY 1 AAPL EQUITY MARKET session=NORMAL duration=DAY"
