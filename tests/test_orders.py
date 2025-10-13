import asyncio
import datetime
from enum import Enum
from typing import Any

from schwab_mcp.tools import orders


class DummyOrdersClient:
    class Order:
        Status = Enum(
            "Status",
            "WORKING FILLED CANCELED REJECTED",
        )

    async def get_orders_for_account(self, *args, **kwargs):
        return None


def run(coro):
    return asyncio.run(coro)


def test_get_orders_maps_single_status_and_dates(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(orders, "call", fake_call)

    client = DummyOrdersClient()
    result = run(
        orders.get_orders(
            client,
            "abc123",
            max_results=25,
            from_date="2024-04-01",
            to_date="2024-04-15",
            status="working",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_orders_for_account

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("abc123",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["max_results"] == 25
    assert kwargs["from_entered_datetime"] == datetime.date(2024, 4, 1)
    assert kwargs["to_entered_datetime"] == datetime.date(2024, 4, 15)
    assert kwargs["status"] is client.Order.Status.WORKING


def test_get_orders_maps_status_list(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(orders, "call", fake_call)

    client = DummyOrdersClient()
    result = run(
        orders.get_orders(
            client,
            "xyz789",
            status=["filled", "canceled"],
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_orders_for_account

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("xyz789",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "status" not in kwargs
    assert kwargs["statuses"] == [
        client.Order.Status.FILLED,
        client.Order.Status.CANCELED,
    ]
