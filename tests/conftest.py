from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from schwab.client import AsyncClient

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.db import NoOpDatabaseManager


class DummyApprovalManager(ApprovalManager):
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED


def make_ctx(client: Any, db: Any = None) -> SchwabContext:
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=DummyApprovalManager(),
        db=db or NoOpDatabaseManager(),
    )
    request_context = SimpleNamespace(lifespan_context=lifespan_context)
    return SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def ctx_factory():
    return make_ctx


@pytest.fixture
def fake_call_capture():
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    return captured, fake_call


@pytest.fixture
def fake_call_factory():
    """Factory fixture for creating fake call mocks with optional return values.

    Returns a factory function that creates (captured_dict, fake_call) tuples.
    The fake_call function captures function calls for test assertions.

    Args:
        return_value: Optional value to return from fake_call (default: "ok")

    Returns:
        Tuple of (captured dict, async fake_call function)
    """

    def factory(return_value: Any = "ok"):
        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            captured["kwargs"] = kwargs
            return return_value

        return captured, fake_call

    return factory


class DummyOrderResponse:
    """Mock HTTP response for order placement."""

    def __init__(self, account_hash: str = "default_hash", order_id: int = 123456789):
        self.status_code = 201
        self.url = f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders"
        self.text = ""
        self.content = b""
        self.headers = {
            "Location": f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders/{order_id}"
        }
        self.is_error = False

    def raise_for_status(self) -> None:
        """No-op method for compatibility with requests.Response."""
        return None


@pytest.fixture
def order_response_factory():
    """Factory fixture for creating DummyOrderResponse instances."""

    def factory(account_hash: str = "default_hash", order_id: int = 123456789):
        return DummyOrderResponse(account_hash=account_hash, order_id=order_id)

    return factory


class DummyPlaceOrderClient:
    """Mock client for place_order() method testing."""

    def __init__(self, order_response: Any):
        self.captured: dict[str, Any] | None = None
        self._response = order_response

    async def place_order(self, *args: Any, **kwargs: Any) -> Any:
        """Capture call arguments and return mock response."""
        self.captured = {"args": args, "kwargs": kwargs}
        return self._response


@pytest.fixture
def place_order_client_factory(order_response_factory):
    """Factory fixture for creating DummyPlaceOrderClient instances."""

    def factory(account_hash: str = "default_hash", order_id: int = 123456789):
        response = order_response_factory(account_hash=account_hash, order_id=order_id)
        return DummyPlaceOrderClient(order_response=response)

    return factory
