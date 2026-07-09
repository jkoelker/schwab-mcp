import datetime
from enum import Enum
from typing import Any

import pytest

from schwab_mcp.tools import orders
from schwab_mcp.tools.utils import SchwabAPIError

from conftest import make_ctx, run


class DummyOrdersClient:
    class Order:
        Status = Enum(
            "Status",
            "WORKING FILLED CANCELED REJECTED",
        )

    async def get_orders_for_account(self, *args, **kwargs):
        return None


class TestNormalizeDuration:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("DAY", "DAY"),
            ("day", "DAY"),
            ("GOOD_TILL_CANCEL", "GOOD_TILL_CANCEL"),
            ("GTC", "GOOD_TILL_CANCEL"),
            ("gtc", "GOOD_TILL_CANCEL"),
            (" GTC ", "GOOD_TILL_CANCEL"),
            ("FILL_OR_KILL", "FILL_OR_KILL"),
            ("FOK", "FILL_OR_KILL"),
            ("IOC", "IMMEDIATE_OR_CANCEL"),
            ("IMMEDIATE_OR_CANCEL", "IMMEDIATE_OR_CANCEL"),
            ("END_OF_WEEK", "END_OF_WEEK"),
        ],
    )
    def test_resolves_valid_values_and_aliases(self, raw, expected):
        assert orders._normalize_duration(raw) == expected

    def test_rejects_unknown_value_with_helpful_message(self):
        with pytest.raises(ValueError, match="Invalid duration: 'BOGUS'"):
            orders._normalize_duration("BOGUS")

    def test_rejects_non_string_with_helpful_message(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            orders._normalize_duration(123)  # type: ignore[arg-type]

    def test_accepts_duration_enum_instance(self):
        assert (
            orders._normalize_duration(orders.Duration.GOOD_TILL_CANCEL)
            == "GOOD_TILL_CANCEL"
        )

    def test_empty_string_raises_before_api_call(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            orders._prepare_equity_order(
                "AAPL",
                50,
                "buy",
                "limit",
                price=175.00,
                duration="",
            )


class TestGetOrders:
    def test_maps_single_status_and_dates(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            captured["kwargs"] = kwargs
            return "ok"

        monkeypatch.setattr(orders, "call", fake_call)

        client = DummyOrdersClient()
        ctx = make_ctx(client)
        result = run(
            orders.get_orders(
                ctx,
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

    def test_maps_status_list(self, monkeypatch):
        # Multiple statuses require separate API calls (schwab-py limitation)
        calls: list[dict[str, Any]] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "args": args, "kwargs": kwargs.copy()})
            # Return realistic order data with unique orderId per status
            status_val = kwargs.get("status")
            if status_val:
                return [{"orderId": f"order_{status_val.name}"}]
            return []

        monkeypatch.setattr(orders, "call", fake_call)

        client = DummyOrdersClient()
        ctx = make_ctx(client)
        result = run(
            orders.get_orders(
                ctx,
                "xyz789",
                status=["filled", "canceled"],
            )
        )

        # Should make two separate calls (one per status)
        assert len(calls) == 2
        assert calls[0]["func"] == client.get_orders_for_account
        assert calls[1]["func"] == client.get_orders_for_account

        # Each call should have a single status (not statuses plural)
        assert calls[0]["kwargs"]["status"] == client.Order.Status.FILLED
        assert calls[1]["kwargs"]["status"] == client.Order.Status.CANCELED

        # Results should be merged and deduplicated
        assert isinstance(result, list)
        assert len(result) == 2
        order_ids = {order["orderId"] for order in result}
        assert order_ids == {"order_FILLED", "order_CANCELED"}


class TestGetOrder:
    def test_calls_client_with_correct_args(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs
            return {"orderId": "12345", "status": "FILLED"}

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def get_order(self, *args, **kwargs):
                return None

        client = DummyClient()
        ctx = make_ctx(client)
        result = run(orders.get_order(ctx, "hash123", "order456"))

        assert result == {"orderId": "12345", "status": "FILLED"}
        assert captured["func"] == client.get_order
        assert captured["kwargs"]["account_hash"] == "hash123"
        assert captured["kwargs"]["order_id"] == "order456"


class TestGetOrderCompact:
    _RAW_ORDER: dict[str, Any] = {
        "orderId": "99",
        "status": "FILLED",
        "quantity": 10.0,
        "filledQuantity": 10.0,
        "remainingQuantity": 0.0,
        "price": 1.5,
        "stopPrice": None,
        "orderType": "LIMIT",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "enteredTime": "2024-04-01T10:00:00Z",
        "closeTime": "2024-04-01T10:01:00Z",
        # noise fields
        "requestedDestination": "AUTO",
        "destinationLinkName": "ETMM",
        "tag": "sometag",
        "accountNumber": "abc123",
        "complexOrderStrategyType": "NONE",
        "cancelable": False,
        "editable": False,
        "orderActivityCollection": [
            {
                "activityType": "EXECUTION",
                "executionLegs": [{"price": 1.5, "quantity": 10}],
            }
        ],
        "orderLegCollection": [
            {
                "orderLegType": "EQUITY",
                "legId": 1,
                "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                "instruction": "BUY",
                "positionEffect": "OPENING",
                "quantity": 10.0,
            }
        ],
        "childOrderStrategies": [
            {
                "orderId": "100",
                "status": "WORKING",
                "quantity": 10.0,
                "filledQuantity": 0.0,
                "remainingQuantity": 10.0,
                "price": 2.0,
                "stopPrice": None,
                "orderType": "LIMIT",
                "session": "NORMAL",
                "duration": "GTC",
                "orderStrategyType": "SINGLE",
                "enteredTime": "2024-04-01T10:01:00Z",
                "closeTime": None,
                # noise
                "requestedDestination": "AUTO",
                "tag": "childtag",
                "orderActivityCollection": [],
                "orderLegCollection": [
                    {
                        "orderLegType": "EQUITY",
                        "legId": 1,
                        "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        "instruction": "SELL",
                        "positionEffect": "CLOSING",
                        "quantity": 10.0,
                    }
                ],
            }
        ],
    }

    def test_compact_default_prunes_noise(self, monkeypatch):
        async def fake_call(func, *args, **kwargs):
            return dict(self._RAW_ORDER)

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def get_order(self, *args, **kwargs):
                return None

        ctx = make_ctx(DummyClient())
        result = run(orders.get_order(ctx, "hash123", "99"))

        assert isinstance(result, dict)
        # Compact fields kept
        assert result["orderId"] == "99"
        assert result["status"] == "FILLED"
        assert result["orderType"] == "LIMIT"
        # Noise fields dropped
        assert "requestedDestination" not in result
        assert "destinationLinkName" not in result
        assert "tag" not in result
        assert "orderActivityCollection" not in result
        assert "accountNumber" not in result
        # legs summary present
        assert result["legs"] == [
            {"symbol": "AAPL", "instruction": "BUY", "quantity": 10.0}
        ]
        # child order also pruned
        assert "childOrderStrategies" in result
        child = result["childOrderStrategies"][0]
        assert child["orderId"] == "100"
        assert child["status"] == "WORKING"
        assert "requestedDestination" not in child
        assert "tag" not in child
        assert "orderActivityCollection" not in child
        assert child["legs"] == [
            {"symbol": "AAPL", "instruction": "SELL", "quantity": 10.0}
        ]

    def test_verbose_returns_raw_payload(self, monkeypatch):
        raw = dict(self._RAW_ORDER)

        async def fake_call(func, *args, **kwargs):
            return raw

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def get_order(self, *args, **kwargs):
                return None

        ctx = make_ctx(DummyClient())
        result = run(orders.get_order(ctx, "hash123", "99", verbose=True))

        assert result is raw
        assert "requestedDestination" in result
        assert "orderActivityCollection" in result


class TestGetOrdersCompact:
    def test_compact_default_prunes_list(self, monkeypatch):
        raw_orders = [
            {
                "orderId": "1",
                "status": "FILLED",
                "quantity": 5.0,
                "filledQuantity": 5.0,
                "remainingQuantity": 0.0,
                "price": 10.0,
                "stopPrice": None,
                "orderType": "LIMIT",
                "session": "NORMAL",
                "duration": "DAY",
                "orderStrategyType": "SINGLE",
                "enteredTime": "2024-04-01T10:00:00Z",
                "closeTime": "2024-04-01T10:01:00Z",
                # noise
                "requestedDestination": "AUTO",
                "tag": "noise",
                "orderActivityCollection": [],
                "orderLegCollection": [
                    {
                        "instrument": {"symbol": "MSFT"},
                        "instruction": "BUY",
                        "quantity": 5.0,
                    }
                ],
            }
        ]

        async def fake_call(func, *args, **kwargs):
            return raw_orders

        monkeypatch.setattr(orders, "call", fake_call)

        ctx = make_ctx(DummyOrdersClient())
        result = run(orders.get_orders(ctx, "hash123"))

        assert isinstance(result, list)
        assert len(result) == 1
        order = result[0]
        assert order["orderId"] == "1"
        assert "requestedDestination" not in order
        assert "tag" not in order
        assert "orderActivityCollection" not in order
        assert order["legs"] == [
            {"symbol": "MSFT", "instruction": "BUY", "quantity": 5.0}
        ]

    def test_verbose_returns_raw_list(self, monkeypatch):
        raw_orders = [{"orderId": "1", "status": "FILLED", "tag": "noise"}]

        async def fake_call(func, *args, **kwargs):
            return raw_orders

        monkeypatch.setattr(orders, "call", fake_call)

        ctx = make_ctx(DummyOrdersClient())
        result = run(orders.get_orders(ctx, "hash123", verbose=True))

        assert result is raw_orders
        assert result[0]["tag"] == "noise"


class TestCancelOrder:
    def test_calls_client_with_correct_args(self, monkeypatch):
        sample_order = {
            "orderId": "order456",
            "status": "CANCELED",
            "quantity": 10,
            "filledQuantity": 0,
        }
        calls: list[Any] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            if len(calls) == 1:
                return None  # cancel_order response
            return sample_order  # get_order response

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def cancel_order(self, *args, **kwargs):
                return None

            async def get_order(self, *args, **kwargs):
                return sample_order

        client = DummyClient()
        ctx = make_ctx(client)
        result = run(orders.cancel_order(ctx, "hash123", "order456"))

        assert len(calls) == 2
        assert calls[0]["func"] == client.cancel_order
        assert calls[0]["kwargs"]["account_hash"] == "hash123"
        assert calls[0]["kwargs"]["order_id"] == "order456"
        assert calls[1]["func"] == client.get_order
        assert calls[1]["kwargs"]["account_hash"] == "hash123"
        assert calls[1]["kwargs"]["order_id"] == "order456"
        # sample_order only contains compact fields, so pruning is a no-op.
        assert result == sample_order

    def test_returns_fallback_when_get_order_returns_no_data(self, monkeypatch):
        calls: list[Any] = []

        async def fake_call(func, *args, **kwargs):
            calls.append(func)
            if len(calls) == 1:
                return None  # cancel_order succeeds
            return None  # get_order returns empty body (e.g. 204)

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def cancel_order(self, *args, **kwargs):
                return None

            async def get_order(self, *args, **kwargs):
                return None

        client = DummyClient()
        ctx = make_ctx(client)
        result = run(orders.cancel_order(ctx, "hash123", "order456"))

        assert result == {
            "orderId": "order456",
            "status": "PENDING_CANCEL",
            "note": "Cancel submitted; status fetch failed",
        }

    def test_returns_fallback_when_get_order_fails(self, monkeypatch):
        calls: list[Any] = []

        async def fake_call(func, *args, **kwargs):
            calls.append(func)
            if len(calls) == 1:
                return None  # cancel_order succeeds
            raise SchwabAPIError(status_code=404, url="/order", body="not found")

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def cancel_order(self, *args, **kwargs):
                return None

            async def get_order(self, *args, **kwargs):
                return None

        client = DummyClient()
        ctx = make_ctx(client)
        result = run(orders.cancel_order(ctx, "hash123", "order456"))

        assert result == {
            "orderId": "order456",
            "status": "PENDING_CANCEL",
            "note": "Cancel submitted; status fetch failed",
        }

    def test_cancel_order_error_propagates_without_get_order(self, monkeypatch):
        calls: list[Any] = []

        async def fake_call(func, *args, **kwargs):
            calls.append(func)
            raise SchwabAPIError(status_code=400, url="/cancel", body="bad request")

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def cancel_order(self, *args, **kwargs):
                return None

            async def get_order(self, *args, **kwargs):
                return None

        client = DummyClient()
        ctx = make_ctx(client)

        with pytest.raises(SchwabAPIError):
            run(orders.cancel_order(ctx, "hash123", "order456"))

        # Only cancel_order was called, not get_order
        assert len(calls) == 1


class TestPlacePreviewedOrder:
    """Tests for the place_previewed_order tool (Phase 3)."""

    @pytest.fixture
    def account_hash(self):
        return "acct_abc123"

    @pytest.fixture
    def order_spec(self):
        return {
            "orderType": "LIMIT",
            "orderStrategyType": "SINGLE",
            "price": "150.00",
            "orderLegCollection": [
                {
                    "instruction": "BUY",
                    "quantity": 100,
                    "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                }
            ],
        }

    def _put_entry(self, ctx, account_hash, order_spec):
        """Helper to pre-populate the preview store and return the preview_id."""
        return ctx.previews.put(
            account_hash,
            order_spec,
            "preview_equity_order",
            "BUY 100 AAPL LIMIT @ $150.00",
        )

    def test_approved_submits_cached_spec(self, monkeypatch, account_hash, order_spec):
        """Happy path: approved decision calls place_order with the exact cached
        spec, then fetches and returns the placed order's details."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        placed_order = {
            "orderId": 42,
            "status": "WORKING",
            "quantity": 100,
            "filledQuantity": 0,
        }
        calls: list[dict] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            if len(calls) == 1:
                return {"orderId": 42, "accountHash": account_hash}
            return placed_order

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.APPROVED

        monkeypatch.setattr(orders_mod, "call", fake_call)
        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        result = run(orders.place_previewed_order(ctx, account_hash, preview_id))

        assert result == orders._prune_order(placed_order)
        assert len(calls) == 2
        # PreviewStore.put() deep-copies the spec (see #130), so this is an
        # equality check rather than identity: what matters is that the
        # exact previewed content is submitted, not re-derived from params.
        assert calls[0]["kwargs"]["order_spec"] == order_spec
        assert calls[0]["kwargs"]["account_hash"] == account_hash
        # orderId from the place response is an int; the get_order call must
        # receive it stringified since get_order's order_id param is typed str.
        assert calls[1]["kwargs"]["order_id"] == "42"
        assert calls[1]["kwargs"]["account_hash"] == account_hash

    def test_returns_fallback_when_get_order_fails(
        self, monkeypatch, account_hash, order_spec
    ):
        """If the post-placement get_order fetch fails, fall back to a minimal
        note instead of masking the successful placement."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod
        from schwab_mcp.tools.utils import SchwabAPIError

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        calls: list[dict] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            if len(calls) == 1:
                return {"orderId": 42, "accountHash": account_hash}
            raise SchwabAPIError(status_code=404, url="/order", body="not found")

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.APPROVED

        monkeypatch.setattr(orders_mod, "call", fake_call)
        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        result = run(orders.place_previewed_order(ctx, account_hash, preview_id))

        assert result == {
            "orderId": "42",
            "accountHash": account_hash,
            "note": "Order placed; status fetch failed",
        }

    def test_returns_fallback_when_get_order_raises_value_error(
        self, monkeypatch, account_hash, order_spec
    ):
        """If the post-placement get_order fetch raises ValueError (e.g. the
        Schwab endpoint returned a non-JSON body), fall back to a minimal
        note instead of letting the error mask the successful placement."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        calls: list[dict] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            if len(calls) == 1:
                return {"orderId": 42, "accountHash": account_hash}
            raise ValueError("Expected JSON response from Schwab endpoint")

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.APPROVED

        monkeypatch.setattr(orders_mod, "call", fake_call)
        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        result = run(orders.place_previewed_order(ctx, account_hash, preview_id))

        assert result == {
            "orderId": "42",
            "accountHash": account_hash,
            "note": "Order placed; status fetch failed",
        }

    def test_returns_fallback_when_get_order_returns_no_data(
        self, monkeypatch, account_hash, order_spec
    ):
        """If the post-placement get_order fetch returns no data (e.g. empty
        body), fall back to a minimal note instead of masking the successful
        placement."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        calls: list[dict] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            if len(calls) == 1:
                return {"orderId": 42, "accountHash": account_hash}
            return None

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.APPROVED

        monkeypatch.setattr(orders_mod, "call", fake_call)
        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        result = run(orders.place_previewed_order(ctx, account_hash, preview_id))

        assert result == {
            "orderId": "42",
            "accountHash": account_hash,
            "note": "Order placed; status fetch failed",
        }

    def test_no_order_id_skips_get_order(self, monkeypatch, account_hash, order_spec):
        """If the place_order response has no extractable orderId (only a
        Location header), return that payload without attempting get_order."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        calls: list[dict] = []

        async def fake_call(func, *args, **kwargs):
            calls.append({"func": func, "kwargs": kwargs})
            return {"location": "https://api.schwabapi.com/orders/123"}

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.APPROVED

        monkeypatch.setattr(orders_mod, "call", fake_call)
        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        result = run(orders.place_previewed_order(ctx, account_hash, preview_id))

        assert result == {"location": "https://api.schwabapi.com/orders/123"}
        assert len(calls) == 1

    def test_denied_raises_permission_error(
        self, monkeypatch, account_hash, order_spec
    ):
        """DENIED decision raises PermissionError."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.DENIED

        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        with pytest.raises(PermissionError, match="denied"):
            run(orders.place_previewed_order(ctx, account_hash, preview_id))

    def test_expired_raises_timeout_error(self, monkeypatch, account_hash, order_spec):
        """EXPIRED decision raises TimeoutError."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.EXPIRED

        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        with pytest.raises(TimeoutError, match="expired"):
            run(orders.place_previewed_order(ctx, account_hash, preview_id))

    def test_pop_before_approval_denied_consumes_entry(
        self, monkeypatch, account_hash, order_spec
    ):
        """After a DENIED decision the entry is consumed; a second call raises ValueError."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        async def fake_run_approval(ctx, request):
            return ApprovalDecision.DENIED

        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        with pytest.raises(PermissionError):
            run(orders.place_previewed_order(ctx, account_hash, preview_id))

        # Entry already consumed — must raise ValueError, not re-trigger approval
        with pytest.raises(ValueError, match="not found or expired"):
            run(orders.place_previewed_order(ctx, account_hash, preview_id))

    def test_account_hash_mismatch_checked_before_approval(
        self, monkeypatch, account_hash, order_spec
    ):
        """Mismatched account_hash raises ValueError before run_approval is called."""
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        async def fake_run_approval(ctx, request):
            raise AssertionError("run_approval must not be called for mismatched hash")

        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        with pytest.raises(ValueError, match="Account hash mismatch"):
            run(orders.place_previewed_order(ctx, "WRONG_HASH", preview_id))

    def test_unknown_preview_id_raises_value_error(self, account_hash):
        """Unknown preview_id raises ValueError immediately."""
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        with pytest.raises(ValueError, match="not found or expired"):
            run(orders.place_previewed_order(ctx, account_hash, "deadbeef"))

    def test_approval_request_includes_summary(
        self, monkeypatch, account_hash, order_spec
    ):
        """The ApprovalRequest sent to run_approval contains the human-readable summary."""
        from schwab_mcp.approvals import ApprovalDecision
        from schwab_mcp.tools import orders as orders_mod

        client = DummyPreviewClient()
        ctx = make_ctx(client)
        preview_id = self._put_entry(ctx, account_hash, order_spec)

        captured_request: list = []

        async def fake_run_approval(ctx, request):
            captured_request.append(request)
            return ApprovalDecision.DENIED

        monkeypatch.setattr(orders_mod, "run_approval", fake_run_approval)

        with pytest.raises(PermissionError):
            run(orders.place_previewed_order(ctx, account_hash, preview_id))

        req = captured_request[0]
        assert req.tool_name == "place_previewed_order"
        assert req.arguments["original_tool"] == "preview_equity_order"
        assert "BUY 100 AAPL" in req.arguments["order_summary"]
        assert req.arguments["preview_id"] == preview_id
        assert req.arguments["account_hash"] == account_hash


# ---------------------------------------------------------------------------
# Additional _prepare_* validation coverage (regression net post-Phase 3)
# The old place_* tests covered these paths; now tested via _prepare_* directly.
# ---------------------------------------------------------------------------


class TestPrepareEquityOrderValidation:
    def test_invalid_order_type_raises(self):
        with pytest.raises(ValueError, match="Invalid order_type"):
            orders._prepare_equity_order("AAPL", 100, "BUY", "BOGUS")

    def test_invalid_instruction_raises(self):
        with pytest.raises(ValueError, match="Invalid instruction"):
            orders._prepare_equity_order("AAPL", 100, "HOLD", "MARKET")

    def test_applies_session_and_duration(self):
        spec = orders._prepare_equity_order(
            "AAPL", 50, "BUY", "LIMIT", price=175.0, session="AM", duration="GTC"
        )
        assert spec["session"] == "AM"
        assert spec["duration"] == "GOOD_TILL_CANCEL"

    def test_limit_order_correct_spec(self):
        spec = orders._prepare_equity_order("SPY", 100, "buy", "limit", price=150.0)
        assert spec["orderType"] == "LIMIT"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY"
        assert spec["orderLegCollection"][0]["quantity"] == 100


class TestPrepareOptionOrderValidation:
    def test_invalid_order_type_raises(self):
        with pytest.raises(ValueError, match="Invalid order_type"):
            orders._prepare_option_order("SPY_C400", 1, "BUY_TO_OPEN", "STOP")

    def test_invalid_instruction_raises(self):
        with pytest.raises(ValueError, match="Invalid instruction"):
            orders._prepare_option_order("SPY_C400", 1, "BUY", "MARKET")


class TestPrepareTrailingStopOrderValidation:
    def test_invalid_trail_type_raises(self):
        with pytest.raises(ValueError, match="Invalid trail_type"):
            orders._prepare_trailing_stop_order("AAPL", 50, "SELL", 5.0, "BOGUS")

    def test_defaults_trail_type_to_value(self):
        spec = orders._prepare_trailing_stop_order("TSLA", 50, "SELL", 5.0)
        assert spec["stopPriceLinkType"] == "VALUE"

    def test_parametrized_trail_types(self):
        for trail_type in ("VALUE", "PERCENT"):
            spec = orders._prepare_trailing_stop_order(
                "AAPL", 10, "SELL", 3.0, trail_type
            )
            assert spec["stopPriceLinkType"] == trail_type


class TestPrepareOcoOrderValidation:
    _GOOD_FIRST: dict[str, Any] = {
        "symbol": "SPY",
        "quantity": 100,
        "instruction": "SELL",
        "order_type": "LIMIT",
        "price": 160.0,
    }
    _GOOD_SECOND: dict[str, Any] = {
        "symbol": "SPY",
        "quantity": 100,
        "instruction": "SELL",
        "order_type": "STOP",
        "stop_price": 140.0,
    }

    def test_invalid_first_order_raises_with_prefix(self):
        bad_first: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
        }
        with pytest.raises(ValueError, match="first_order:"):
            orders._prepare_oco_order(bad_first, self._GOOD_SECOND)

    def test_invalid_second_order_raises_with_prefix(self):
        bad_second: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "STOP",
        }
        with pytest.raises(ValueError, match="second_order:"):
            orders._prepare_oco_order(self._GOOD_FIRST, bad_second)

    def test_correct_spec_structure(self):
        spec = orders._prepare_oco_order(self._GOOD_FIRST, self._GOOD_SECOND)
        assert spec["orderStrategyType"] == "OCO"
        assert len(spec["childOrderStrategies"]) == 2


class TestPrepareTriggerOrderValidation:
    _ENTRY: dict[str, Any] = {
        "symbol": "SPY",
        "quantity": 100,
        "instruction": "BUY",
        "order_type": "MARKET",
    }

    def test_wrong_exit_count_raises(self):
        with pytest.raises(ValueError, match="exit_orders must contain 1 or 2 orders"):
            orders._prepare_trigger_order(self._ENTRY, [])

    def test_invalid_entry_raises_with_prefix(self):
        bad_entry: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "LIMIT",
        }
        exit_order: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="entry_order:"):
            orders._prepare_trigger_order(bad_entry, [exit_order])

    def test_invalid_exit_raises_with_index_prefix(self):
        bad_exit: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "LIMIT",
            # price missing
        }
        with pytest.raises(ValueError, match=r"exit_orders\[0\]:"):
            orders._prepare_trigger_order(self._ENTRY, [bad_exit])


class TestPrepareBracketOrderValidation:
    def test_neither_price_raises(self):
        with pytest.raises(
            ValueError, match="At least one of profit_price or loss_price"
        ):
            orders._prepare_bracket_order("SPY", 100, "BUY", "MARKET")

    def test_invalid_entry_instruction_raises(self):
        with pytest.raises(ValueError, match="Invalid entry_instruction: HOLD"):
            orders._prepare_bracket_order(
                "SPY", 100, "HOLD", "MARKET", profit_price=160.0
            )

    def test_stop_only_structure(self):
        spec = orders._prepare_bracket_order(
            "SPY", 100, "BUY", "MARKET", loss_price=140.0
        )
        assert spec["orderStrategyType"] == "TRIGGER"
        child = spec["childOrderStrategies"][0]
        assert child["orderType"] == "STOP"

    def test_profit_only_structure(self):
        spec = orders._prepare_bracket_order(
            "SPY", 100, "BUY", "MARKET", profit_price=160.0
        )
        child = spec["childOrderStrategies"][0]
        assert child["orderType"] == "LIMIT"

    def test_full_bracket_has_oco_child(self):
        spec = orders._prepare_bracket_order(
            "SPY", 100, "BUY", "MARKET", profit_price=160.0, loss_price=140.0
        )
        oco_child = spec["childOrderStrategies"][0]
        assert oco_child["orderStrategyType"] == "OCO"

    def test_exit_session_duration_override(self):
        spec = orders._prepare_bracket_order(
            "SPY",
            100,
            "BUY",
            "MARKET",
            profit_price=160.0,
            loss_price=140.0,
            session="NORMAL",
            duration="DAY",
            exit_session="NORMAL",
            exit_duration="GOOD_TILL_CANCEL",
        )
        assert spec["duration"] == "DAY"
        oco_child = spec["childOrderStrategies"][0]
        for exit_order in oco_child["childOrderStrategies"]:
            assert exit_order["duration"] == "GOOD_TILL_CANCEL"

    def test_loss_type_limit(self):
        spec = orders._prepare_bracket_order(
            "SPY", 100, "BUY", "MARKET", loss_price=140.0, loss_type="LIMIT"
        )
        child = spec["childOrderStrategies"][0]
        assert child["orderType"] == "LIMIT"
        assert float(child["price"]) == 140.0
        assert "stopPrice" not in child

    def test_loss_type_stop_limit(self):
        spec = orders._prepare_bracket_order(
            "SPY",
            100,
            "BUY",
            "MARKET",
            loss_price=140.0,
            loss_type="STOP_LIMIT",
            loss_limit_price=139.5,
        )
        child = spec["childOrderStrategies"][0]
        assert child["orderType"] == "STOP_LIMIT"
        assert float(child["stopPrice"]) == 140.0
        assert float(child["price"]) == 139.5

    def test_stop_limit_without_loss_limit_price_raises(self):
        with pytest.raises(ValueError, match="loss_limit_price"):
            orders._prepare_bracket_order(
                "SPY",
                100,
                "BUY",
                "MARKET",
                loss_price=140.0,
                loss_type="STOP_LIMIT",
            )

    def test_stop_with_loss_limit_price_raises(self):
        with pytest.raises(ValueError, match="loss_limit_price"):
            orders._prepare_bracket_order(
                "SPY",
                100,
                "BUY",
                "MARKET",
                loss_price=140.0,
                loss_type="STOP",
                loss_limit_price=139.5,
            )

    def test_invalid_loss_type_raises(self):
        with pytest.raises(ValueError, match="Invalid loss_type"):
            orders._prepare_bracket_order(
                "SPY", 100, "BUY", "MARKET", loss_price=140.0, loss_type="GTC"
            )

    def test_loss_type_without_loss_price_raises(self):
        with pytest.raises(ValueError, match="loss_type/loss_limit_price"):
            orders._prepare_bracket_order(
                "SPY", 100, "BUY", "MARKET", profit_price=160.0, loss_type="LIMIT"
            )

    def test_loss_limit_price_without_loss_price_raises(self):
        with pytest.raises(ValueError, match="loss_type/loss_limit_price"):
            orders._prepare_bracket_order(
                "SPY",
                100,
                "BUY",
                "MARKET",
                profit_price=160.0,
                loss_limit_price=139.5,
            )


class TestPrepareOptionComboOrderValidation:
    def test_requires_at_least_two_legs(self):
        with pytest.raises(ValueError, match="at least two option legs"):
            orders._prepare_option_combo_order(
                [{"instruction": "BUY_TO_OPEN", "symbol": "SPY_C500", "quantity": 1}],
                "NET_DEBIT",
            )

    def test_correct_spec_structure(self):
        legs = [
            {"instruction": "BUY_TO_OPEN", "symbol": "SPY 251219C500", "quantity": 1},
            {"instruction": "SELL_TO_OPEN", "symbol": "SPY 251219C510", "quantity": 1},
        ]
        spec = orders._prepare_option_combo_order(legs, "NET_DEBIT", price=2.50)
        assert spec["orderStrategyType"] == "SINGLE"
        assert spec["orderType"] == "NET_DEBIT"
        assert len(spec["orderLegCollection"]) == 2


class TestBuildOrderFromDesc:
    """Tests for the _build_order_from_desc dispatcher."""

    def test_equity_market_order(self):
        desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "MARKET"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY"
        assert spec["orderLegCollection"][0]["instrument"]["symbol"] == "AAPL"

    def test_equity_limit_order(self):
        desc: dict[str, Any] = {
            "symbol": "SPY",
            "quantity": 5,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 450.00,
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "LIMIT"
        assert float(spec["price"]) == 450.00

    def test_equity_stop_order(self):
        desc: dict[str, Any] = {
            "symbol": "TSLA",
            "quantity": 2,
            "instruction": "SELL",
            "order_type": "STOP",
            "stop_price": 200.00,
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "STOP"
        assert float(spec["stopPrice"]) == 200.00

    def test_equity_stop_limit_order(self):
        desc: dict[str, Any] = {
            "symbol": "NVDA",
            "quantity": 3,
            "instruction": "BUY",
            "order_type": "STOP_LIMIT",
            "price": 800.00,
            "stop_price": 795.00,
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "STOP_LIMIT"
        assert float(spec["price"]) == 800.00
        assert float(spec["stopPrice"]) == 795.00

    def test_option_buy_to_open_market(self):
        desc: dict[str, Any] = {
            "symbol": "SPY 251219C500",
            "quantity": 1,
            "instruction": "BUY_TO_OPEN",
            "order_type": "MARKET",
            "asset_type": "OPTION",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "MARKET"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY_TO_OPEN"

    def test_option_sell_to_close_limit(self):
        desc: dict[str, Any] = {
            "symbol": "SPY 251219C500",
            "quantity": 2,
            "instruction": "SELL_TO_CLOSE",
            "order_type": "LIMIT",
            "price": 3.50,
            "asset_type": "OPTION",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "LIMIT"
        assert float(spec["price"]) == 3.50
        assert spec["orderLegCollection"][0]["instruction"] == "SELL_TO_CLOSE"

    def test_trailing_stop_value(self):
        desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "TRAILING_STOP",
            "trail_offset": 5.0,
            "trail_type": "VALUE",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["orderType"] == "TRAILING_STOP"
        assert spec["stopPriceOffset"] == 5.0
        assert spec["stopPriceLinkType"] == "VALUE"

    def test_trailing_stop_percent(self):
        desc: dict[str, Any] = {
            "symbol": "TSLA",
            "quantity": 5,
            "instruction": "SELL",
            "order_type": "TRAILING_STOP",
            "trail_offset": 3.0,
            "trail_type": "PERCENT",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["stopPriceLinkType"] == "PERCENT"

    def test_missing_required_field_raises(self):
        # Order-leg dicts arrive as untrusted MCP tool-call JSON, not Python
        # literals, so required keys are checked explicitly at runtime (via
        # OrderDesc.from_dict()) and raise a descriptive ValueError rather
        # than a bare KeyError.
        bad_desc = {"symbol": "AAPL", "quantity": 10, "instruction": "BUY"}
        with pytest.raises(ValueError, match="order_type"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_missing_multiple_required_fields_raises(self):
        bad_desc = {"symbol": "AAPL"}
        with pytest.raises(ValueError, match="quantity.*instruction.*order_type"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    @pytest.mark.parametrize("field", ["price", "stop_price", "trail_offset"])
    def test_non_numeric_optional_field_raises(self, field):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "LIMIT",
            field: "not-a-number",
        }
        with pytest.raises(ValueError, match=f"{field} must be a number"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_non_string_trail_type_raises(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "TRAILING_STOP",
            "trail_offset": 1.0,
            "trail_type": 123,
        }
        with pytest.raises(ValueError, match="trail_type must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    @pytest.mark.parametrize("field", ["session", "duration"])
    def test_non_string_session_or_duration_raises(self, field):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            field: 123,
        }
        with pytest.raises(ValueError, match=f"{field} must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_trailing_stop_with_option_raises(self):
        desc: dict[str, Any] = {
            "symbol": "SPY 251219C500",
            "quantity": 1,
            "instruction": "SELL_TO_CLOSE",
            "order_type": "TRAILING_STOP",
            "trail_offset": 2.0,
            "asset_type": "OPTION",
        }
        with pytest.raises(ValueError, match="TRAILING_STOP.*not supported.*OPTION"):
            orders._build_order_from_desc(desc, "NORMAL", "DAY")

    def test_per_leg_session_overrides_default(self):
        desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            "session": "AM",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["session"] == "AM"

    def test_per_leg_duration_overrides_default(self):
        desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            "duration": "GOOD_TILL_CANCEL",
        }
        builder = orders._build_order_from_desc(desc, "NORMAL", "DAY")
        spec = builder.build()
        assert spec["duration"] == "GOOD_TILL_CANCEL"

    def test_trailing_stop_missing_trail_offset_raises(self):
        desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 5,
            "instruction": "SELL",
            "order_type": "TRAILING_STOP",
        }
        with pytest.raises(
            ValueError, match="TRAILING_STOP orders require 'trail_offset'"
        ):
            orders._build_order_from_desc(desc, "NORMAL", "DAY")

    def test_non_string_order_type_raises_value_error(self):
        # Untrusted MCP tool-call JSON could pass a non-string (e.g. null or
        # a number); this must raise a descriptive ValueError, not an
        # AttributeError from calling .upper() on a non-string.
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": None,
        }
        with pytest.raises(ValueError, match="order_type must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_non_string_asset_type_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            "asset_type": 123,
        }
        with pytest.raises(ValueError, match="asset_type must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_invalid_asset_type_raises_value_error(self):
        bad_desc: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            "asset_type": "OPTON",  # misspelled, must not silently fall back to EQUITY
        }
        with pytest.raises(ValueError, match="Invalid asset_type: OPTON"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_non_string_symbol_raises_value_error(self):
        bad_desc = {
            "symbol": 12345,
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="symbol must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_non_int_quantity_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": "ten",
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="quantity must be an integer"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_bool_quantity_raises_value_error(self):
        # bool is a subclass of int in Python; reject it explicitly so a
        # stray true/false in tool-call JSON doesn't silently become qty 1/0.
        bad_desc = {
            "symbol": "AAPL",
            "quantity": True,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="quantity must be an integer"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")

    def test_non_string_instruction_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": None,
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="instruction must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")


class TestCreateOptionSymbol:
    @pytest.mark.parametrize(
        ("underlying", "expiration", "contract_type", "strike", "expected"),
        [
            ("SPY", "251219", "C", "500", "SPY   251219C00500000"),
            ("SPY", "251219", "P", "500", "SPY   251219P00500000"),
            ("AAPL", "240315", "CALL", "175", "AAPL  240315C00175000"),
            ("AAPL", "240315", "PUT", "170", "AAPL  240315P00170000"),
            ("TSLA", "250117", "C", "250.5", "TSLA  250117C00250500"),
        ],
    )
    def test_creates_valid_option_symbol(
        self, underlying, expiration, contract_type, strike, expected
    ):
        result = run(
            orders.create_option_symbol(underlying, expiration, contract_type, strike)
        )
        assert result == expected


class TestOrderResponseHandler:
    @pytest.fixture
    def make_response(self):
        def _make(
            account_hash: str, order_id: int | None, include_location: bool = True
        ):
            class DummyResponse:
                is_error = False
                status_code = 201

                def __init__(self):
                    self.headers = {}
                    if include_location and order_id is not None:
                        self.headers["Location"] = (
                            f"https://api.schwabapi.com/trader/v1/accounts/"
                            f"{account_hash}/orders/{order_id}"
                        )
                    elif include_location:
                        self.headers["Location"] = (
                            "https://api.schwabapi.com/trader/v1/some/other/path"
                        )

            return DummyResponse()

        return _make

    def test_extracts_order_id_from_location_header(self, make_response):
        account_hash = "test_hash"
        order_id = 123456789

        response = make_response(account_hash, order_id)
        ctx = make_ctx(DummyOrdersClient())
        handler = orders._order_response_handler(ctx, account_hash)

        handled, payload = handler(response)

        assert handled is True
        assert isinstance(payload, dict)
        assert payload["orderId"] == order_id
        assert payload["accountHash"] == account_hash
        assert "location" in payload

    def test_returns_false_when_no_order_id_or_location(self, make_response):
        account_hash = "test_hash"

        response = make_response(account_hash, None, include_location=False)
        ctx = make_ctx(DummyOrdersClient())
        handler = orders._order_response_handler(ctx, account_hash)

        handled, payload = handler(response)

        assert handled is False
        assert payload is None

    def test_handles_location_only_without_extractable_order_id(self, make_response):
        account_hash = "test_hash"

        response = make_response(account_hash, None, include_location=True)
        ctx = make_ctx(DummyOrdersClient())
        handler = orders._order_response_handler(ctx, account_hash)

        handled, payload = handler(response)

        assert handled is True
        assert isinstance(payload, dict)
        assert "location" in payload
        assert "orderId" not in payload


# ---------------------------------------------------------------------------
# Fix #5: _order_legs_summary type guards for non-dict legs / instrument
# ---------------------------------------------------------------------------


class TestOrderLegsSummaryTypeGuards:
    def test_skips_non_dict_legs(self):
        """Non-dict entries in orderLegCollection must be silently skipped."""
        order: dict[str, Any] = {
            "orderLegCollection": [
                "not-a-dict",
                42,
                {"instrument": {"symbol": "AAPL"}, "instruction": "BUY", "quantity": 5},
            ]
        }
        result = orders._order_legs_summary(order)
        assert result == [{"symbol": "AAPL", "instruction": "BUY", "quantity": 5}]

    def test_instrument_not_dict_yields_none_symbol(self):
        """When instrument is not a dict, symbol must be None (not raise)."""
        order: dict[str, Any] = {
            "orderLegCollection": [
                {"instrument": None, "instruction": "SELL", "quantity": 3},
            ]
        }
        result = orders._order_legs_summary(order)
        assert result == [{"symbol": None, "instruction": "SELL", "quantity": 3}]

    def test_instrument_missing_yields_none_symbol(self):
        """When instrument key is absent, symbol must be None."""
        order: dict[str, Any] = {
            "orderLegCollection": [
                {"instruction": "BUY", "quantity": 10},
            ]
        }
        result = orders._order_legs_summary(order)
        assert result == [{"symbol": None, "instruction": "BUY", "quantity": 10}]


# ---------------------------------------------------------------------------
# Fix #6: _prune_order validates list types before processing
# ---------------------------------------------------------------------------


class TestPruneOrderTypeGuards:
    def test_order_leg_collection_as_dict_not_processed(self):
        """orderLegCollection that is a dict (not a list) must not add legs key."""
        order: dict[str, Any] = {
            "orderId": "1",
            "status": "WORKING",
            "orderLegCollection": {"unexpected": "dict"},
        }
        result = orders._prune_order(order)
        assert isinstance(result, dict)
        assert "legs" not in result.keys()

    def test_child_order_strategies_as_dict_not_processed(self):
        """childOrderStrategies that is a dict must not add childOrderStrategies key."""
        order: dict[str, Any] = {
            "orderId": "2",
            "status": "WORKING",
            "childOrderStrategies": {"unexpected": "dict"},
        }
        result = orders._prune_order(order)
        assert isinstance(result, dict)
        assert "childOrderStrategies" not in result.keys()

    def test_empty_order_leg_collection_list_omits_legs_key(self):
        """An empty orderLegCollection list must not add a legs key."""
        order: dict[str, Any] = {
            "orderId": "3",
            "status": "FILLED",
            "orderLegCollection": [],
        }
        result = orders._prune_order(order)
        assert isinstance(result, dict)
        assert "legs" not in result.keys()

    def test_all_non_dict_legs_omits_legs_key(self):
        """When all legs are non-dict, the resulting summary is empty, so legs key is omitted."""
        order: dict[str, Any] = {
            "orderId": "4",
            "status": "FILLED",
            "orderLegCollection": ["bad", 99],
        }
        result = orders._prune_order(order)
        assert isinstance(result, dict)
        assert "legs" not in result.keys()

    def test_non_dict_order_passes_through(self):
        """Non-dict input to _prune_order must be returned unchanged."""
        assert orders._prune_order("raw") == "raw"
        assert orders._prune_order(None) is None


# ---------------------------------------------------------------------------
# Phase 2: preview_* tools
# ---------------------------------------------------------------------------


class DummyPreviewClient:
    """Mock client that supports both place_order and preview_order."""

    def __init__(self):
        self.captured: dict[str, Any] | None = None

    async def preview_order(self, *args: Any, **kwargs: Any) -> Any:
        self.captured = {"args": args, "kwargs": kwargs}
        return {"orderId": 999, "orderStrategy": {}, "orderValidationResult": {}}

    async def place_order(self, *args: Any, **kwargs: Any) -> Any:
        self.captured = {"args": args, "kwargs": kwargs}
        return {}

    async def get_order(self, *args: Any, **kwargs: Any) -> Any:
        return {}


class TestPreviewEquityOrder:
    def test_returns_preview_id_preview_and_action(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs
            return {"orderId": 42}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_equity_order(
                ctx, "acc123", "AAPL", 100, "BUY", "LIMIT", price=150.0
            )
        )

        assert isinstance(result, dict)
        assert "preview_id" in result
        assert "preview" in result
        assert "action" in result
        assert "acc123" in result["action"]
        assert result["preview_id"] in result["action"]

    def test_calls_preview_order_with_correct_spec(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        run(
            orders.preview_equity_order(
                ctx, "acc123", "AAPL", 100, "BUY", "LIMIT", price=150.0
            )
        )

        assert captured["func"] == client.preview_order
        assert captured["kwargs"]["account_hash"] == "acc123"
        spec = captured["kwargs"]["order_spec"]
        assert spec["orderType"] == "LIMIT"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY"
        assert spec["orderLegCollection"][0]["quantity"] == 100

    def test_stores_entry_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_equity_order(
                ctx, "acc123", "AAPL", 100, "BUY", "LIMIT", price=150.0
            )
        )

        preview_id = result["preview_id"]
        entry = ctx.previews.pop(preview_id, "acc123")
        assert entry.account_hash == "acc123"
        assert entry.tool_name == "preview_equity_order"
        assert entry.order_spec["orderType"] == "LIMIT"

    def test_rejects_invalid_order_type(self):
        client = DummyPreviewClient()
        ctx = make_ctx(client)
        with pytest.raises(ValueError, match="Invalid order_type"):
            run(orders.preview_equity_order(ctx, "acc123", "AAPL", 100, "BUY", "BOGUS"))


class TestPreviewOptionOrder:
    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {"orderId": 77}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_option_order(
                ctx, "acc123", "SPY 230616C400", 1, "BUY_TO_OPEN", "LIMIT", price=2.50
            )
        )

        assert "preview_id" in result
        assert "preview" in result
        assert "action" in result

    def test_rejects_invalid_instruction(self):
        client = DummyPreviewClient()
        ctx = make_ctx(client)
        with pytest.raises(ValueError, match="Invalid instruction"):
            run(
                orders.preview_option_order(
                    ctx, "acc123", "SPY 230616C400", 1, "BOGUS", "LIMIT", price=2.50
                )
            )

    def test_stores_correct_spec_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_option_order(
                ctx, "acc123", "SPY 230616C400", 2, "BUY_TO_OPEN", "LIMIT", price=3.0
            )
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_option_order"
        assert entry.order_spec["orderLegCollection"][0]["quantity"] == 2


class TestPreviewEquityTrailingStopOrder:
    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_equity_trailing_stop_order(
                ctx, "acc123", "AAPL", 50, "SELL", trail_offset=5.0
            )
        )

        assert "preview_id" in result
        assert "action" in result

    def test_stores_entry_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_equity_trailing_stop_order(
                ctx, "acc123", "AAPL", 50, "SELL", trail_offset=5.0
            )
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_equity_trailing_stop_order"
        assert "AAPL" in entry.summary


class TestPreviewOcoOrder:
    _LIMIT_LEG: dict[str, Any] = {
        "symbol": "AAPL",
        "quantity": 100,
        "instruction": "SELL",
        "order_type": "LIMIT",
        "price": 160.0,
    }
    _STOP_LEG: dict[str, Any] = {
        "symbol": "AAPL",
        "quantity": 100,
        "instruction": "SELL",
        "order_type": "STOP",
        "stop_price": 140.0,
    }

    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_oco_order(ctx, "acc123", self._LIMIT_LEG, self._STOP_LEG)  # type: ignore[arg-type]
        )

        assert "preview_id" in result
        assert "preview" in result

    def test_stores_entry_with_correct_tool_name(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_oco_order(ctx, "acc123", self._LIMIT_LEG, self._STOP_LEG)  # type: ignore[arg-type]
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_oco_order"
        assert "OCO" in entry.summary


class TestPreviewTriggerOrder:
    def _make_leg(
        self, instruction: str = "BUY", order_type: str = "MARKET"
    ) -> dict[str, Any]:
        return {
            "symbol": "AAPL",
            "quantity": 100,
            "instruction": instruction,
            "order_type": order_type,
        }

    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        exit_leg: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 160.0,
        }
        result = run(
            orders.preview_trigger_order(ctx, "acc123", self._make_leg(), [exit_leg])  # type: ignore[arg-type]
        )

        assert "preview_id" in result
        assert "action" in result

    def test_stores_entry_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        exit_leg: dict[str, Any] = {
            "symbol": "AAPL",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 160.0,
        }
        result = run(
            orders.preview_trigger_order(ctx, "acc123", self._make_leg(), [exit_leg])  # type: ignore[arg-type]
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_trigger_order"
        assert "TRIGGER" in entry.summary

    def test_rejects_invalid_exit_count(self):
        client = DummyPreviewClient()
        ctx = make_ctx(client)
        with pytest.raises(ValueError, match="exit_orders must contain"):
            run(orders.preview_trigger_order(ctx, "acc123", self._make_leg(), []))  # type: ignore[arg-type]


class TestPreviewBracketOrder:
    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_bracket_order(
                ctx,
                "acc123",
                "AAPL",
                100,
                "BUY",
                "MARKET",
                profit_price=160.0,
                loss_price=140.0,
            )
        )

        assert "preview_id" in result
        assert "preview" in result

    def test_stores_entry_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_bracket_order(
                ctx,
                "acc123",
                "AAPL",
                100,
                "BUY",
                "MARKET",
                profit_price=160.0,
                loss_price=140.0,
            )
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_bracket_order"
        assert "BRACKET" in entry.summary
        assert "AAPL" in entry.summary

    def test_rejects_missing_exit_prices(self):
        client = DummyPreviewClient()
        ctx = make_ctx(client)
        with pytest.raises(
            ValueError, match="At least one of profit_price or loss_price"
        ):
            run(
                orders.preview_bracket_order(
                    ctx, "acc123", "AAPL", 100, "BUY", "MARKET"
                )
            )

    def test_resolved_leg_types_full_bracket_default_loss(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_bracket_order(
                ctx,
                "acc123",
                "AAPL",
                100,
                "BUY",
                "MARKET",
                profit_price=160.0,
                loss_price=140.0,
            )
        )

        assert result["resolved_leg_types"] == {
            "entry": "MARKET",
            "profit": "LIMIT",
            "loss": "STOP",
        }

    def test_resolved_leg_types_loss_limit_no_profit(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_bracket_order(
                ctx,
                "acc123",
                "AAPL",
                100,
                "BUY",
                "MARKET",
                loss_price=140.0,
                loss_type="LIMIT",
            )
        )

        assert result["resolved_leg_types"] == {"entry": "MARKET", "loss": "LIMIT"}

    def test_resolved_leg_types_stop_limit_loss(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_bracket_order(
                ctx,
                "acc123",
                "AAPL",
                100,
                "BUY",
                "MARKET",
                loss_price=140.0,
                loss_type="STOP_LIMIT",
                loss_limit_price=139.0,
            )
        )

        assert result["resolved_leg_types"]["loss"] == "STOP_LIMIT"
        assert "preview_id" in result


class TestPreviewOptionComboOrder:
    _LEGS = [
        {"instruction": "SELL_TO_OPEN", "symbol": "SPY 251121C500", "quantity": 1},
        {"instruction": "BUY_TO_OPEN", "symbol": "SPY 251121C510", "quantity": 1},
    ]

    def test_returns_preview_shape(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_option_combo_order(
                ctx, "acc123", self._LEGS, "NET_CREDIT", price=1.0
            )
        )

        assert "preview_id" in result
        assert "preview" in result
        assert "action" in result

    def test_stores_entry_in_previews(self, monkeypatch):
        client = DummyPreviewClient()
        ctx = make_ctx(client)

        async def fake_call(func, *args, **kwargs):
            return {}

        monkeypatch.setattr(orders, "call", fake_call)

        result = run(
            orders.preview_option_combo_order(
                ctx, "acc123", self._LEGS, "NET_CREDIT", price=1.0
            )
        )

        entry = ctx.previews.pop(result["preview_id"], "acc123")
        assert entry.tool_name == "preview_option_combo_order"
        assert "COMBO" in entry.summary
        assert "NET_CREDIT" in entry.summary

    def test_rejects_single_leg(self):
        client = DummyPreviewClient()
        ctx = make_ctx(client)
        with pytest.raises(ValueError, match="at least two option legs"):
            run(
                orders.preview_option_combo_order(
                    ctx, "acc123", [self._LEGS[0]], "NET_CREDIT", price=1.0
                )
            )
