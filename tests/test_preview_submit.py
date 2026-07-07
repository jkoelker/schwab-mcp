from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from schwab.client import AsyncClient

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools import orders

from conftest import make_ctx, run


class DummyPreviewClient:
    """Mock client for preview_order()/place_order() testing."""

    def __init__(self, preview_response: Any = None, place_response: Any = None):
        self.preview_response = preview_response
        self.place_response = place_response
        self.preview_calls: list[dict[str, Any]] = []
        self.place_calls: list[dict[str, Any]] = []

    async def preview_order(self, **kwargs: Any) -> Any:
        self.preview_calls.append(kwargs)
        return DummyResponse(self.preview_response)

    async def place_order(self, **kwargs: Any) -> Any:
        self.place_calls.append(kwargs)
        return self.place_response


class DummyResponse:
    def __init__(self, payload: Any, *, status_code: int = 200):
        self.status_code = status_code
        self.url = "https://example.invalid"
        self.text = ""
        self.is_error = False
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class RecordingApprovalManager(ApprovalManager):
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision


class DummySession:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_log_message(self, **payload: Any) -> None:
        self.messages.append(payload)

    async def send_progress_notification(self, **_: Any) -> None:
        pass


def make_submit_ctx(
    client: Any, decision: ApprovalDecision
) -> tuple[SchwabContext, RecordingApprovalManager, DummySession]:
    approval_manager = RecordingApprovalManager(decision)
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=approval_manager,
    )
    session = DummySession()
    request_context = SimpleNamespace(
        lifespan_context=lifespan_context,
        request_id="req-1",
        session=session,
        meta=None,
    )
    ctx = SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )
    return ctx, approval_manager, session


class TestPreviewOrder:
    def test_stores_preview_and_returns_id_and_summary(self):
        client = DummyPreviewClient(preview_response={"orderStrategy": "ok"})
        ctx = make_ctx(client)
        order_spec = {
            "orderType": "LIMIT",
            "price": "150.0",
            "orderLegCollection": [
                {
                    "instruction": "BUY",
                    "quantity": 10,
                    "instrument": {"symbol": "AAPL"},
                }
            ],
        }

        result = run(orders.preview_order(ctx, "hash1", order_spec))

        assert result["preview"] == {"orderStrategy": "ok"}
        assert result["summary"] == "BUY 10 AAPL LIMIT @ 150.0"
        assert result["preview_id"]

        # The exact spec that was previewed is retrievable by the returned ID.
        entry = ctx.previews.peek(result["preview_id"])
        assert entry.order_spec == order_spec
        assert entry.account_hash == "hash1"
        assert client.preview_calls == [
            {"account_hash": "hash1", "order_spec": order_spec}
        ]

    def test_falls_back_to_placeholder_summary_for_unparseable_spec(self):
        client = DummyPreviewClient(preview_response={})
        ctx = make_ctx(client)

        result = run(orders.preview_order(ctx, "hash1", {"weird": "shape"}))

        assert result["summary"] == orders._FALLBACK_ORDER_SUMMARY

    def test_summarizes_oco_spec_by_recursing_child_order_strategies(self):
        client = DummyPreviewClient(preview_response={})
        ctx = make_ctx(client)
        oco_spec = {
            "orderStrategyType": "OCO",
            "childOrderStrategies": [
                {
                    "orderType": "LIMIT",
                    "price": "160.0",
                    "orderLegCollection": [
                        {
                            "instruction": "SELL",
                            "quantity": 5,
                            "instrument": {"symbol": "MSFT"},
                        }
                    ],
                },
                {
                    "orderType": "STOP",
                    "stopPrice": "140.0",
                    "orderLegCollection": [
                        {
                            "instruction": "SELL",
                            "quantity": 5,
                            "instrument": {"symbol": "MSFT"},
                        }
                    ],
                },
            ],
        }

        result = run(orders.preview_order(ctx, "hash1", oco_spec))

        assert (
            result["summary"]
            == "SELL 5 MSFT LIMIT @ 160.0; SELL 5 MSFT STOP stop@140.0"
        )

    def test_summarizes_stop_limit_leg_with_both_prices(self):
        client = DummyPreviewClient(preview_response={})
        ctx = make_ctx(client)
        order_spec = {
            "orderType": "STOP_LIMIT",
            "price": "145.0",
            "stopPrice": "150.0",
            "orderLegCollection": [
                {
                    "instruction": "SELL",
                    "quantity": 20,
                    "instrument": {"symbol": "TSLA"},
                }
            ],
        }

        result = run(orders.preview_order(ctx, "hash1", order_spec))

        assert result["summary"] == "SELL 20 TSLA STOP_LIMIT stop@150.0 @ 145.0"

    def test_flags_leg_missing_required_fields_instead_of_rendering_none(self):
        client = DummyPreviewClient(preview_response={})
        ctx = make_ctx(client)
        order_spec = {
            "orderType": "MARKET",
            "orderLegCollection": [{"instrument": {"symbol": "AAPL"}}],
        }

        result = run(orders.preview_order(ctx, "hash1", order_spec))

        assert result["summary"] == orders._FALLBACK_LEG_SUMMARY
        assert "None" not in result["summary"]


class TestSubmitPreviewedOrder:
    def _seed_preview(self, ctx: SchwabContext, account_hash: str = "hash1") -> str:
        order_spec = {
            "orderLegCollection": [
                {
                    "instruction": "BUY",
                    "quantity": 1,
                    "instrument": {"symbol": "AAPL"},
                }
            ]
        }
        entry = ctx.previews.put(account_hash, order_spec, {"ok": True}, "BUY 1 AAPL")
        return entry.preview_id

    def test_approved_submits_stored_order_spec_and_pops_entry(
        self, order_response_factory
    ):
        place_response = order_response_factory(account_hash="hash1", order_id=987654)
        client = DummyPreviewClient(place_response=place_response)
        ctx, approval_manager, session = make_submit_ctx(
            client, ApprovalDecision.APPROVED
        )
        preview_id = self._seed_preview(ctx)

        result = run(orders.submit_previewed_order(ctx, "hash1", preview_id))

        assert result["orderId"] == 987654
        assert client.place_calls[0]["order_spec"] == {
            "orderLegCollection": [
                {
                    "instruction": "BUY",
                    "quantity": 1,
                    "instrument": {"symbol": "AAPL"},
                }
            ]
        }
        # Reviewer saw a resolved summary, not just the opaque preview_id.
        assert approval_manager.requests[0].arguments["order_summary"] == "BUY 1 AAPL"
        # One-time use: the preview is gone after a successful submit.
        with pytest.raises(ValueError, match="not found"):
            ctx.previews.peek(preview_id)
        assert session.messages == []

    def test_denied_raises_permission_error_and_leaves_preview_untouched(self):
        client = DummyPreviewClient()
        ctx, approval_manager, session = make_submit_ctx(
            client, ApprovalDecision.DENIED
        )
        preview_id = self._seed_preview(ctx)

        with pytest.raises(PermissionError):
            run(orders.submit_previewed_order(ctx, "hash1", preview_id))

        assert client.place_calls == []
        assert session.messages[0]["level"] == "warning"
        # Denied approvals don't consume the preview -- it can be resubmitted.
        assert ctx.previews.peek(preview_id).preview_id == preview_id

    def test_expired_decision_raises_timeout_error(self):
        client = DummyPreviewClient()
        ctx, _approval_manager, session = make_submit_ctx(
            client, ApprovalDecision.EXPIRED
        )
        preview_id = self._seed_preview(ctx)

        with pytest.raises(TimeoutError):
            run(orders.submit_previewed_order(ctx, "hash1", preview_id))

        assert client.place_calls == []
        assert session.messages[0]["level"] == "warning"

    def test_unknown_preview_id_raises_before_requesting_approval(self):
        client = DummyPreviewClient()
        ctx, approval_manager, _session = make_submit_ctx(
            client, ApprovalDecision.APPROVED
        )

        with pytest.raises(ValueError, match="not found"):
            run(orders.submit_previewed_order(ctx, "hash1", "does-not-exist"))

        assert approval_manager.requests == []

    def test_expiry_during_approval_deliberation_raises_on_pop(self):
        """TOCTOU: peek succeeds pre-approval (preview is fresh), but if the TTL
        elapses while the reviewer is deliberating, the post-approval pop must
        fail closed rather than silently submitting a stale preview."""
        client = DummyPreviewClient()
        preview_id_holder: dict[str, str] = {}

        class ExpiringDuringApprovalManager(ApprovalManager):
            """Backdates the preview's created_at while "reviewing" it, to
            simulate the TTL elapsing during a slow approval decision."""

            async def require(self, request: ApprovalRequest) -> ApprovalDecision:
                import dataclasses

                store = ctx.schwab.preview_store
                preview_id = preview_id_holder["id"]
                entries = store._entries  # noqa: SLF001 - test-only introspection
                entries[preview_id] = dataclasses.replace(
                    entries[preview_id],
                    created_at=datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=1),
                )
                return ApprovalDecision.APPROVED

        lifespan_context = SchwabServerContext(
            client=cast(AsyncClient, client),
            approval_manager=ExpiringDuringApprovalManager(),
        )
        session = DummySession()
        request_context = SimpleNamespace(
            lifespan_context=lifespan_context,
            request_id="req-1",
            session=session,
            meta=None,
        )
        ctx = SchwabContext.model_construct(
            _request_context=cast(Any, request_context),
            _fastmcp=None,
        )
        entry = ctx.previews.put(
            "hash1",
            {
                "orderLegCollection": [
                    {
                        "instruction": "BUY",
                        "quantity": 1,
                        "instrument": {"symbol": "AAPL"},
                    }
                ]
            },
            {},
            "BUY 1 AAPL",
        )
        preview_id_holder["id"] = entry.preview_id

        with pytest.raises(ValueError, match="expired"):
            run(orders.submit_previewed_order(ctx, "hash1", entry.preview_id))

        assert client.place_calls == []

    def test_account_hash_mismatch_raises_before_requesting_approval(self):
        client = DummyPreviewClient()
        ctx, approval_manager, _session = make_submit_ctx(
            client, ApprovalDecision.APPROVED
        )
        preview_id = self._seed_preview(ctx, account_hash="hash1")

        with pytest.raises(ValueError, match="different account_hash"):
            run(orders.submit_previewed_order(ctx, "hash2", preview_id))

        assert approval_manager.requests == []
        # Preview is untouched -- caller can retry with the correct account_hash.
        assert ctx.previews.peek(preview_id).preview_id == preview_id


def test_run_helper_is_reused_from_conftest():
    # Sanity check that this module's imports line up with conftest's helpers.
    assert asyncio.iscoroutinefunction(orders.submit_previewed_order)
