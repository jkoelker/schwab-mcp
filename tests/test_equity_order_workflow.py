from __future__ import annotations

from enum import Enum
from typing import Any

import httpx
import pytest
from conftest import make_ctx, run

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools import orders

ACCOUNT_HASH = "acct123"
SYMBOL = "MSFT"
QUANTITY = 3
ORDER_ID = "987654321"

EXPECTED_ORDER_SPEC: dict[str, Any] = {
    "session": "NORMAL",
    "duration": "DAY",
    "orderType": "MARKET",
    "orderStrategyType": "SINGLE",
    "orderLegCollection": [
        {
            "instruction": "BUY",
            "quantity": 3,
            "instrument": {"symbol": "MSFT", "assetType": "EQUITY"},
        }
    ],
}

PREVIEW_PAYLOAD = {
    "orderValidationResult": {"type": "ACCEPTED"},
    "projectedOrder": {"orderType": "MARKET", "status": "WORKING"},
}

ORDER_DETAILS = {
    "orderId": int(ORDER_ID),
    "status": "WORKING",
    "quantity": QUANTITY,
    "filledQuantity": 0,
    "remainingQuantity": QUANTITY,
    "orderType": "MARKET",
    "session": "NORMAL",
    "duration": "DAY",
    "orderStrategyType": "SINGLE",
    "routingDetails": {"internalOnly": "not returned"},
    "orderLegCollection": [
        {
            "instruction": "BUY",
            "quantity": QUANTITY,
            "instrument": {"symbol": SYMBOL, "assetType": "EQUITY"},
        }
    ],
}


class EquityOrdersClient:
    """Narrow Schwab API fake that returns real HTTPX responses."""

    class Instrument:
        Projection = Enum("Projection", {"SYMBOL_SEARCH": "symbol-search"})

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.preview_submissions: list[tuple[str, dict[str, Any]]] = []
        self.placed_submissions: list[tuple[str, dict[str, Any]]] = []
        self.status_lookups: list[tuple[str, str]] = []
        self.instrument_lookups: list[str] = []

    async def get_instruments(self, symbol: str, **kwargs: Any) -> httpx.Response:
        """Serve the preview flow's assetType guard; every equity symbol resolves EQUITY."""
        self.events.append("instrument_resolved")
        self.instrument_lookups.append(symbol)
        request = httpx.Request(
            "GET",
            f"https://api.schwabapi.com/marketdata/v1/instruments?symbol={symbol}",
        )
        return httpx.Response(
            200,
            json={"instruments": [{"symbol": symbol, "assetType": "EQUITY"}]},
            request=request,
        )

    async def preview_order(self, account_hash: str, order_spec: dict[str, Any]) -> httpx.Response:
        self.events.append("preview_submitted")
        self.preview_submissions.append((account_hash, order_spec))
        request = httpx.Request(
            "POST",
            f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/previewOrder",
        )
        return httpx.Response(200, json=PREVIEW_PAYLOAD, request=request)

    async def place_order(self, account_hash: str, order_spec: dict[str, Any]) -> httpx.Response:
        self.events.append("order_placed")
        self.placed_submissions.append((account_hash, order_spec))
        url = f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders"
        request = httpx.Request("POST", url)
        return httpx.Response(
            201,
            headers={"Location": f"{url}/{ORDER_ID}"},
            request=request,
        )

    async def get_order(self, order_id: str, account_hash: str) -> httpx.Response:
        self.events.append("order_status_fetched")
        self.status_lookups.append((order_id, account_hash))
        request = httpx.Request(
            "GET",
            f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders/{order_id}",
        )
        return httpx.Response(200, json=ORDER_DETAILS, request=request)


class RecordingApprovalManager(ApprovalManager):
    def __init__(self, events: list[str], decision: ApprovalDecision) -> None:
        self.events = events
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.events.append("approval_requested")
        self.requests.append(request)
        return self.decision


def make_workflow(
    decision: ApprovalDecision,
) -> tuple[SchwabContext, EquityOrdersClient, RecordingApprovalManager, list[str]]:
    events: list[str] = []
    client = EquityOrdersClient(events)
    approval_manager = RecordingApprovalManager(events, decision)
    ctx = make_ctx(client)
    ctx.schwab.approval_manager = approval_manager
    return ctx, client, approval_manager, events


def assert_approval_request(
    approval_manager: RecordingApprovalManager,
    preview_id: str,
) -> None:
    assert len(approval_manager.requests) == 1
    request = approval_manager.requests[0]
    assert request.tool_name == "place_previewed_order"
    assert request.arguments == {
        "original_tool": "preview_equity_order",
        "order_summary": "BUY 3 MSFT MARKET",
        "preview_id": preview_id,
        "account_hash": ACCOUNT_HASH,
    }


def preview_market_buy(ctx: SchwabContext) -> dict[str, Any]:
    result = run(orders.preview_equity_order(ctx, ACCOUNT_HASH, SYMBOL, QUANTITY, "BUY", "MARKET"))
    assert isinstance(result, dict)
    return result


def test_approved_equity_preview_places_once_and_returns_order_status() -> None:
    ctx, client, approval_manager, events = make_workflow(ApprovalDecision.APPROVED)

    preview = preview_market_buy(ctx)
    preview_id = preview["preview_id"]

    assert preview["preview"] == PREVIEW_PAYLOAD
    assert preview["action"] == (
        f"Call place_previewed_order(account_hash='{ACCOUNT_HASH}', preview_id='{preview_id}') "
        "to execute this exact order."
    )
    assert client.preview_submissions == [(ACCOUNT_HASH, EXPECTED_ORDER_SPEC)]

    result = run(orders.place_previewed_order(ctx, ACCOUNT_HASH, preview_id))

    assert result == {
        "orderId": int(ORDER_ID),
        "status": "WORKING",
        "quantity": QUANTITY,
        "filledQuantity": 0,
        "remainingQuantity": QUANTITY,
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "legs": [{"symbol": SYMBOL, "instruction": "BUY", "quantity": QUANTITY}],
    }
    assert client.placed_submissions == [(ACCOUNT_HASH, EXPECTED_ORDER_SPEC)]
    assert client.status_lookups == [(ORDER_ID, ACCOUNT_HASH)]
    assert events == [
        "instrument_resolved",
        "preview_submitted",
        "approval_requested",
        "order_placed",
        "order_status_fetched",
    ]
    assert_approval_request(approval_manager, preview_id)

    with pytest.raises(ValueError, match="not found or expired"):
        run(orders.place_previewed_order(ctx, ACCOUNT_HASH, preview_id))

    assert len(approval_manager.requests) == 1
    assert client.placed_submissions == [(ACCOUNT_HASH, EXPECTED_ORDER_SPEC)]
    assert events == [
        "instrument_resolved",
        "preview_submitted",
        "approval_requested",
        "order_placed",
        "order_status_fetched",
    ]


def test_wrong_account_cannot_place_equity_preview_or_consume_it() -> None:
    ctx, client, approval_manager, events = make_workflow(ApprovalDecision.APPROVED)

    preview = preview_market_buy(ctx)
    preview_id = preview["preview_id"]

    with pytest.raises(ValueError, match="Account hash mismatch"):
        run(orders.place_previewed_order(ctx, "wrong-account", preview_id))

    assert client.placed_submissions == []
    assert client.status_lookups == []
    assert approval_manager.requests == []
    assert events == ["instrument_resolved", "preview_submitted"]

    result = run(orders.place_previewed_order(ctx, ACCOUNT_HASH, preview_id))

    assert result["orderId"] == int(ORDER_ID)
    assert result["status"] == "WORKING"
    assert client.placed_submissions == [(ACCOUNT_HASH, EXPECTED_ORDER_SPEC)]
    assert client.status_lookups == [(ORDER_ID, ACCOUNT_HASH)]
    assert events == [
        "instrument_resolved",
        "preview_submitted",
        "approval_requested",
        "order_placed",
        "order_status_fetched",
    ]
    assert_approval_request(approval_manager, preview_id)


@pytest.mark.parametrize(
    ("decision", "error", "message"),
    [
        pytest.param(
            ApprovalDecision.DENIED,
            PermissionError,
            "denied by reviewer",
            id="denied",
        ),
        pytest.param(
            ApprovalDecision.EXPIRED,
            TimeoutError,
            "expired",
            id="expired",
        ),
    ],
)
def test_rejected_equity_preview_does_not_place_and_cannot_be_retried(
    decision: ApprovalDecision,
    error: type[Exception],
    message: str,
) -> None:
    ctx, client, approval_manager, events = make_workflow(decision)

    preview = preview_market_buy(ctx)
    preview_id = preview["preview_id"]

    assert preview["preview"] == PREVIEW_PAYLOAD
    assert preview["action"].startswith(
        f"Call place_previewed_order(account_hash='{ACCOUNT_HASH}', preview_id='{preview_id}')"
    )
    assert client.preview_submissions == [(ACCOUNT_HASH, EXPECTED_ORDER_SPEC)]

    with pytest.raises(error, match=message):
        run(orders.place_previewed_order(ctx, ACCOUNT_HASH, preview_id))

    assert_approval_request(approval_manager, preview_id)
    assert client.placed_submissions == []
    assert client.status_lookups == []
    assert events == ["instrument_resolved", "preview_submitted", "approval_requested"]

    with pytest.raises(ValueError, match="not found or expired"):
        run(orders.place_previewed_order(ctx, ACCOUNT_HASH, preview_id))

    assert len(approval_manager.requests) == 1
    assert client.placed_submissions == []
    assert events == ["instrument_resolved", "preview_submitted", "approval_requested"]
