from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from mcp.server.mcpserver import Context as MCPContext, MCPServer
from mcp.server.mcpserver.tools import Tool
from schwab.client import AsyncClient

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabServerContext
from schwab_mcp.tools import orders
from schwab_mcp.tools._registration import register_tool

ACCOUNT_HASH = "account-hash-42"
ORDER_ID = "order-987"


class FixedApprovalManager(ApprovalManager):
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision


class FakeSchwabOrders:
    """A local order endpoint that exposes cancellation as observable state."""

    def __init__(self) -> None:
        self.orders = {
            (ACCOUNT_HASH, ORDER_ID): {
                "orderId": ORDER_ID,
                "status": "WORKING",
                "quantity": 2,
                "filledQuantity": 0,
                "remainingQuantity": 2,
                "internalNote": "not returned to callers",
            }
        }
        self.cancel_mutations: list[tuple[str, str]] = []

    async def cancel_order(self, *, order_id: str, account_hash: str) -> httpx.Response:
        self.cancel_mutations.append((account_hash, order_id))
        self.orders[(account_hash, order_id)]["status"] = "CANCELED"
        request = httpx.Request(
            "DELETE",
            f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders/{order_id}",
        )
        return httpx.Response(204, request=request)

    async def get_order(self, order_id: str, account_hash: str) -> httpx.Response:
        request = httpx.Request(
            "GET",
            f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders/{order_id}",
        )
        return httpx.Response(
            200,
            json=self.orders[(account_hash, order_id)],
            request=request,
        )


def registered_cancel_tool(
    decision: ApprovalDecision,
) -> tuple[Tool, MCPContext, FakeSchwabOrders, FixedApprovalManager]:
    server = MCPServer(name="approval-registration")
    client = FakeSchwabOrders()
    approvals = FixedApprovalManager(decision)
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=approvals,
    )
    request_context = SimpleNamespace(
        lifespan_context=lifespan_context,
        request_id="request-123",
        meta={"client_id": "mcp-client-7"},
    )
    context = MCPContext.model_construct(
        _request_context=cast(Any, request_context),
        _mcp_server=server,
    )

    register_tool(server, orders.cancel_order, write=True)
    tool_manager = getattr(server, "_tool_manager")
    tool = next(tool for tool in cast(list[Tool], tool_manager.list_tools()) if tool.name == "cancel_order")
    return tool, context, client, approvals


def assert_cancel_request(approvals: FixedApprovalManager) -> None:
    assert len(approvals.requests) == 1
    request = approvals.requests[0]
    assert request.tool_name == "cancel_order"
    assert request.arguments == {
        "account_hash": repr(ACCOUNT_HASH),
        "order_id": repr(ORDER_ID),
    }


@pytest.mark.parametrize(
    ("decision", "error", "message"),
    [
        (ApprovalDecision.DENIED, PermissionError, "denied by reviewer"),
        (ApprovalDecision.EXPIRED, TimeoutError, "request for tool 'cancel_order' expired"),
    ],
)
def test_registered_cancel_requires_approval_before_mutation(
    decision: ApprovalDecision,
    error: type[Exception],
    message: str,
) -> None:
    tool, context, client, approvals = registered_cancel_tool(decision)

    annotations = tool.annotations
    assert annotations is not None
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is True

    with pytest.raises(error, match=message):
        asyncio.run(tool.fn(context, ACCOUNT_HASH, ORDER_ID))

    assert_cancel_request(approvals)
    assert client.cancel_mutations == []
    assert client.orders[(ACCOUNT_HASH, ORDER_ID)]["status"] == "WORKING"


def test_registered_cancel_executes_and_returns_updated_order_when_approved() -> None:
    tool, context, client, approvals = registered_cancel_tool(ApprovalDecision.APPROVED)

    annotations = tool.annotations
    assert annotations is not None
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is True

    result = asyncio.run(tool.fn(context, ACCOUNT_HASH, ORDER_ID))

    assert_cancel_request(approvals)
    assert client.cancel_mutations == [(ACCOUNT_HASH, ORDER_ID)]
    assert client.orders[(ACCOUNT_HASH, ORDER_ID)]["status"] == "CANCELED"
    assert result == {
        "orderId": ORDER_ID,
        "status": "CANCELED",
        "quantity": 2,
        "filledQuantity": 0,
        "remainingQuantity": 2,
    }
