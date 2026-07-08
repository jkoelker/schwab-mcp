import datetime
from enum import Enum
from typing import Any

import pytest

from schwab_mcp.tools import orders

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

    def test_empty_string_raises_before_api_call(
        self, monkeypatch, place_order_client_factory
    ):
        place_order_client = place_order_client_factory(account_hash="acc", order_id=1)
        ctx = make_ctx(place_order_client)
        with pytest.raises(ValueError, match="Invalid duration"):
            run(
                orders.place_equity_order(
                    ctx,
                    "acc",
                    "AAPL",
                    50,
                    "buy",
                    "limit",
                    price=175.00,
                    duration="",
                )
            )
        assert place_order_client.captured is None


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
        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs
            return None

        monkeypatch.setattr(orders, "call", fake_call)

        class DummyClient:
            async def cancel_order(self, *args, **kwargs):
                return None

        client = DummyClient()
        ctx = make_ctx(client)
        result = run(orders.cancel_order(ctx, "hash123", "order456"))

        assert result is None
        assert captured["func"] == client.cancel_order
        assert captured["kwargs"]["account_hash"] == "hash123"
        assert captured["kwargs"]["order_id"] == "order456"


class TestPlaceEquityOrder:
    @pytest.fixture
    def account_hash(self):
        return "test_account_hash"

    @pytest.fixture
    def order_id(self):
        return 987654321

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    @pytest.mark.parametrize(
        ("instruction", "order_type", "price", "stop_price", "expected_order_type"),
        [
            ("buy", "market", None, None, "MARKET"),
            ("sell", "market", None, None, "MARKET"),
            ("BUY", "MARKET", None, None, "MARKET"),
            ("SELL", "MARKET", None, None, "MARKET"),
            ("buy", "limit", 150.00, None, "LIMIT"),
            ("sell", "limit", 150.00, None, "LIMIT"),
            ("buy", "stop", None, 145.00, "STOP"),
            ("sell", "stop", None, 145.00, "STOP"),
            ("buy", "stop_limit", 150.00, 145.00, "STOP_LIMIT"),
            ("sell", "stop_limit", 150.00, 145.00, "STOP_LIMIT"),
        ],
    )
    def test_places_order_with_correct_spec(
        self,
        place_order_client,
        account_hash,
        order_id,
        instruction,
        order_type,
        price,
        stop_price,
        expected_order_type,
    ):
        ctx = make_ctx(place_order_client)
        result = run(
            orders.place_equity_order(
                ctx,
                account_hash,
                "SPY",
                100,
                instruction,
                order_type,
                price=price,
                stop_price=stop_price,
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash
        assert "location" in result

        captured = place_order_client.captured
        assert captured is not None
        assert captured["kwargs"]["account_hash"] == account_hash

        order_spec = captured["kwargs"]["order_spec"]
        assert order_spec["orderType"] == expected_order_type
        assert order_spec["orderStrategyType"] == "SINGLE"
        assert order_spec["orderLegCollection"][0]["instruction"] == instruction.upper()
        assert order_spec["orderLegCollection"][0]["quantity"] == 100
        assert order_spec["orderLegCollection"][0]["instrument"]["symbol"] == "SPY"

    def test_applies_session_and_duration(self, place_order_client, account_hash):
        ctx = make_ctx(place_order_client)
        run(
            orders.place_equity_order(
                ctx,
                account_hash,
                "AAPL",
                50,
                "buy",
                "limit",
                price=175.00,
                session="AM",
                duration="GOOD_TILL_CANCEL",
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["session"] == "AM"
        assert order_spec["duration"] == "GOOD_TILL_CANCEL"

    @pytest.mark.parametrize("alias", ["GTC", "gtc", " GTC "])
    def test_gtc_alias_matches_good_till_cancel(
        self, place_order_client, account_hash, alias
    ):
        ctx = make_ctx(place_order_client)
        run(
            orders.place_equity_order(
                ctx,
                account_hash,
                "AAPL",
                50,
                "buy",
                "limit",
                price=175.00,
                duration=alias,
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["duration"] == "GOOD_TILL_CANCEL"

    def test_invalid_duration_raises_before_api_call(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)
        with pytest.raises(ValueError, match="Invalid duration"):
            run(
                orders.place_equity_order(
                    ctx,
                    account_hash,
                    "AAPL",
                    50,
                    "buy",
                    "limit",
                    price=175.00,
                    duration="BOGUS",
                )
            )

        assert place_order_client.captured is None


class TestPlaceOptionOrder:
    @pytest.fixture
    def account_hash(self):
        return "option_account_hash"

    @pytest.fixture
    def order_id(self):
        return 111222333

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    @pytest.mark.parametrize(
        ("instruction", "order_type", "price", "expected_order_type"),
        [
            ("BUY_TO_OPEN", "MARKET", None, "MARKET"),
            ("SELL_TO_OPEN", "MARKET", None, "MARKET"),
            ("BUY_TO_CLOSE", "MARKET", None, "MARKET"),
            ("SELL_TO_CLOSE", "MARKET", None, "MARKET"),
            ("buy_to_open", "market", None, "MARKET"),
            ("BUY_TO_OPEN", "LIMIT", 2.50, "LIMIT"),
            ("SELL_TO_OPEN", "LIMIT", 3.00, "LIMIT"),
            ("BUY_TO_CLOSE", "LIMIT", 1.75, "LIMIT"),
            ("SELL_TO_CLOSE", "LIMIT", 2.25, "LIMIT"),
            ("sell_to_close", "limit", 2.25, "LIMIT"),
        ],
    )
    def test_places_order_with_correct_spec(
        self,
        place_order_client,
        account_hash,
        order_id,
        instruction,
        order_type,
        price,
        expected_order_type,
    ):
        ctx = make_ctx(place_order_client)
        option_symbol = "SPY 251219C500"

        result = run(
            orders.place_option_order(
                ctx,
                account_hash,
                option_symbol,
                5,
                instruction,
                order_type,
                price=price,
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]
        assert order_spec["orderType"] == expected_order_type
        assert order_spec["orderStrategyType"] == "SINGLE"
        assert order_spec["orderLegCollection"][0]["instruction"] == instruction.upper()
        assert order_spec["orderLegCollection"][0]["quantity"] == 5
        assert (
            order_spec["orderLegCollection"][0]["instrument"]["symbol"] == option_symbol
        )
        assert (
            order_spec["orderLegCollection"][0]["instrument"]["assetType"] == "OPTION"
        )


class TestPlaceEquityTrailingStopOrder:
    @pytest.fixture
    def account_hash(self):
        return "trailing_account_hash"

    @pytest.fixture
    def order_id(self):
        return 444555666

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    @pytest.mark.parametrize(
        ("instruction", "trail_type", "trail_offset"),
        [
            ("BUY", "VALUE", 5.00),
            ("SELL", "VALUE", 5.00),
            ("buy", "value", 10.00),
            ("sell", "value", 2.50),
            ("BUY", "PERCENT", 5.0),
            ("SELL", "PERCENT", 3.0),
            ("buy", "percent", 2.5),
            ("sell", "percent", 1.0),
        ],
    )
    def test_places_order_with_correct_spec(
        self,
        place_order_client,
        account_hash,
        order_id,
        instruction,
        trail_type,
        trail_offset,
    ):
        ctx = make_ctx(place_order_client)

        result = run(
            orders.place_equity_trailing_stop_order(
                ctx,
                account_hash,
                "TSLA",
                50,
                instruction,
                trail_offset,
                trail_type=trail_type,
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]
        assert order_spec["orderType"] == "TRAILING_STOP"
        assert order_spec["stopPriceOffset"] == trail_offset
        assert order_spec["stopPriceLinkType"] == trail_type.upper()
        assert order_spec["stopPriceLinkBasis"] == "LAST"
        assert order_spec["orderLegCollection"][0]["instruction"] == instruction.upper()
        assert order_spec["orderLegCollection"][0]["quantity"] == 50

    def test_defaults_trail_type_to_value(self, place_order_client, account_hash):
        ctx = make_ctx(place_order_client)

        run(
            orders.place_equity_trailing_stop_order(
                ctx,
                account_hash,
                "TSLA",
                50,
                "SELL",
                5.00,
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["stopPriceLinkType"] == "VALUE"


class TestPlaceBracketOrder:
    @pytest.fixture
    def account_hash(self):
        return "bracket_account_hash"

    @pytest.fixture
    def order_id(self):
        return 777888999

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    @pytest.mark.parametrize(
        ("entry_instruction", "entry_type", "entry_price", "entry_stop_price"),
        [
            ("BUY", "MARKET", None, None),
            ("SELL", "MARKET", None, None),
            ("BUY", "LIMIT", 150.00, None),
            ("SELL", "LIMIT", 150.00, None),
            ("BUY", "STOP", None, 145.00),
            ("SELL", "STOP", None, 155.00),
            ("BUY", "STOP_LIMIT", 150.00, 145.00),
            ("SELL", "STOP_LIMIT", 150.00, 155.00),
        ],
    )
    def test_places_bracket_order_with_entry_types(
        self,
        place_order_client,
        account_hash,
        order_id,
        entry_instruction,
        entry_type,
        entry_price,
        entry_stop_price,
    ):
        ctx = make_ctx(place_order_client)

        result = run(
            orders.place_bracket_order(
                ctx,
                account_hash,
                "SPY",
                100,
                entry_instruction,
                entry_type,
                profit_price=160.00,
                loss_price=140.00,
                entry_price=entry_price,
                entry_stop_price=entry_stop_price,
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]

        assert order_spec["orderStrategyType"] == "TRIGGER"
        assert "childOrderStrategies" in order_spec

        oco_child = order_spec["childOrderStrategies"][0]
        assert oco_child["orderStrategyType"] == "OCO"
        assert len(oco_child["childOrderStrategies"]) == 2

    def test_bracket_order_exit_instructions_opposite_of_entry(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        run(
            orders.place_bracket_order(
                ctx,
                account_hash,
                "SPY",
                100,
                "BUY",
                "MARKET",
                profit_price=160.00,
                loss_price=140.00,
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        oco_child = order_spec["childOrderStrategies"][0]

        for exit_order in oco_child["childOrderStrategies"]:
            exit_instruction = exit_order["orderLegCollection"][0]["instruction"]
            assert exit_instruction == "SELL"

    def test_bracket_order_invalid_entry_instruction_raises(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        with pytest.raises(ValueError, match="Invalid entry_instruction: HOLD"):
            run(
                orders.place_bracket_order(
                    ctx,
                    account_hash,
                    "SPY",
                    100,
                    "HOLD",
                    "MARKET",
                    profit_price=160.00,
                    loss_price=140.00,
                )
            )

    def test_bracket_order_stop_only_no_oco(self, place_order_client, account_hash):
        """loss_price only: TRIGGER > SINGLE(stop), no OCO wrapper."""
        ctx = make_ctx(place_order_client)

        run(
            orders.place_bracket_order(
                ctx,
                account_hash,
                "SPY",
                100,
                "BUY",
                "MARKET",
                loss_price=140.00,
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["orderStrategyType"] == "TRIGGER"
        assert "childOrderStrategies" in order_spec

        child = order_spec["childOrderStrategies"][0]
        # Must NOT be an OCO wrapper
        assert child.get("orderStrategyType") != "OCO"
        # Must be a single stop order
        assert child["orderType"] == "STOP"
        assert float(child["stopPrice"]) == 140.00
        leg = child["orderLegCollection"][0]
        assert leg["instruction"] == "SELL"

    def test_bracket_order_profit_only_no_oco(self, place_order_client, account_hash):
        """profit_price only: TRIGGER > SINGLE(limit), no OCO wrapper."""
        ctx = make_ctx(place_order_client)

        run(
            orders.place_bracket_order(
                ctx,
                account_hash,
                "SPY",
                100,
                "BUY",
                "MARKET",
                profit_price=160.00,
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["orderStrategyType"] == "TRIGGER"
        assert "childOrderStrategies" in order_spec

        child = order_spec["childOrderStrategies"][0]
        # Must NOT be an OCO wrapper
        assert child.get("orderStrategyType") != "OCO"
        # Must be a single limit order
        assert child["orderType"] == "LIMIT"
        assert float(child["price"]) == 160.00
        leg = child["orderLegCollection"][0]
        assert leg["instruction"] == "SELL"

    def test_bracket_order_neither_price_raises_before_submit(
        self, place_order_client, account_hash
    ):
        """Neither price provided: raises ValueError, client never called."""
        ctx = make_ctx(place_order_client)

        with pytest.raises(
            ValueError,
            match="At least one of profit_price or loss_price must be provided",
        ):
            run(
                orders.place_bracket_order(
                    ctx,
                    account_hash,
                    "SPY",
                    100,
                    "BUY",
                    "MARKET",
                )
            )

        assert place_order_client.captured is None

    def test_bracket_order_exit_session_and_duration_override(
        self, place_order_client, account_hash
    ):
        """exit_session/exit_duration apply to exit legs but not the entry."""
        ctx = make_ctx(place_order_client)

        run(
            orders.place_bracket_order(
                ctx,
                account_hash,
                "SPY",
                100,
                "BUY",
                "MARKET",
                profit_price=160.00,
                loss_price=140.00,
                session="NORMAL",
                duration="DAY",
                exit_session="NORMAL",
                exit_duration="GOOD_TILL_CANCEL",
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["orderStrategyType"] == "TRIGGER"

        # Entry leg (top-level order) should be DAY
        assert order_spec["duration"] == "DAY"

        # Exit legs are nested inside an OCO child strategy
        oco_child = order_spec["childOrderStrategies"][0]
        assert oco_child["orderStrategyType"] == "OCO"
        for exit_order in oco_child["childOrderStrategies"]:
            assert exit_order["duration"] == "GOOD_TILL_CANCEL"

    def test_build_bracket_exit_order_neither_price_raises(self):
        """Defense-in-depth: _build_bracket_exit_order rejects neither-price
        calls even though place_bracket_order already guards against this."""
        with pytest.raises(
            ValueError,
            match="At least one of profit_price or loss_price must be provided",
        ):
            orders._build_bracket_exit_order(
                entry_order_builder=object(),
                symbol="SPY",
                quantity=100,
                exit_instruction="SELL",
                profit_price=None,
                loss_price=None,
                exit_session="NORMAL",
                exit_duration="DAY",
            )


class TestBuildOrderFromDesc:
    """Tests for the _build_order_from_desc dispatcher."""

    def test_equity_market_order(self):
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        # OrderDesc dicts arrive as untrusted MCP tool-call JSON, not Python
        # literals, so required keys are checked explicitly at runtime and
        # raise a descriptive ValueError rather than a bare KeyError.
        bad_desc = {"symbol": "AAPL", "quantity": 10, "instruction": "BUY"}
        with pytest.raises(ValueError, match="order_type"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_missing_multiple_required_fields_raises(self):
        bad_desc = {"symbol": "AAPL"}
        with pytest.raises(ValueError, match="quantity.*instruction.*order_type"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_trailing_stop_with_option_raises(self):
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
        desc: orders.OrderDesc = {
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
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_non_string_asset_type_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
            "asset_type": 123,
        }
        with pytest.raises(ValueError, match="asset_type must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_invalid_asset_type_raises_value_error(self):
        bad_desc: orders.OrderDesc = {
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
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_non_int_quantity_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": "ten",
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="quantity must be an integer"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

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
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]

    def test_non_string_instruction_raises_value_error(self):
        bad_desc = {
            "symbol": "AAPL",
            "quantity": 10,
            "instruction": None,
            "order_type": "MARKET",
        }
        with pytest.raises(ValueError, match="instruction must be a string"):
            orders._build_order_from_desc(bad_desc, "NORMAL", "DAY")  # type: ignore[arg-type]


class TestPlaceOcoOrder:
    @pytest.fixture
    def account_hash(self):
        return "oco_account_hash"

    @pytest.fixture
    def order_id(self):
        return 123123123

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    def test_places_oco_order_with_two_children(
        self, place_order_client, account_hash, order_id
    ):
        ctx = make_ctx(place_order_client)

        first_order: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 160.00,
        }
        second_order: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "STOP",
            "stop_price": 140.00,
        }

        result = run(
            orders.place_oco_order(ctx, account_hash, first_order, second_order)
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]

        assert order_spec["orderStrategyType"] == "OCO"
        assert len(order_spec["childOrderStrategies"]) == 2
        assert order_spec["childOrderStrategies"][0]["orderType"] == "LIMIT"
        assert order_spec["childOrderStrategies"][1]["orderType"] == "STOP"

    def test_invalid_first_order_raises_with_prefix(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        bad_first: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
            # price missing
        }
        good_second: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "STOP",
            "stop_price": 140.00,
        }

        with pytest.raises(ValueError, match="first_order:"):
            run(orders.place_oco_order(ctx, account_hash, bad_first, good_second))

    def test_invalid_second_order_raises_with_prefix(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        good_first: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 160.00,
        }
        bad_second: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "SELL",
            "order_type": "STOP",
            # stop_price missing
        }

        with pytest.raises(ValueError, match="second_order:"):
            run(orders.place_oco_order(ctx, account_hash, good_first, bad_second))

    def test_oco_order_uses_default_session_and_duration(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        first_order: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "LIMIT",
            "price": 160.00,
        }
        second_order: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "SELL",
            "order_type": "STOP",
            "stop_price": 140.00,
        }

        run(
            orders.place_oco_order(
                ctx,
                account_hash,
                first_order,
                second_order,
                session="AM",
                duration="GTC",
            )
        )

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        # Both children should have AM session and GOOD_TILL_CANCEL duration
        for child in order_spec["childOrderStrategies"]:
            assert child["session"] == "AM"
            assert child["duration"] == "GOOD_TILL_CANCEL"


class TestPlaceTriggerOrder:
    @pytest.fixture
    def account_hash(self):
        return "trigger_account_hash"

    @pytest.fixture
    def order_id(self):
        return 456456456

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    def test_places_trigger_with_single_exit(
        self, place_order_client, account_hash, order_id
    ):
        ctx = make_ctx(place_order_client)

        entry: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "BUY",
            "order_type": "LIMIT",
            "price": 145.00,
        }
        exits = [
            orders.OrderDesc(
                symbol="SPY",
                quantity=100,
                instruction="SELL",
                order_type="LIMIT",
                price=160.00,
            )
        ]

        result = run(orders.place_trigger_order(ctx, account_hash, entry, exits))

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]

        assert order_spec["orderStrategyType"] == "TRIGGER"
        assert "childOrderStrategies" in order_spec
        assert len(order_spec["childOrderStrategies"]) == 1
        assert order_spec["orderLegCollection"][0]["instruction"] == "BUY"
        child = order_spec["childOrderStrategies"][0]
        assert child["orderLegCollection"][0]["instruction"] == "SELL"

    def test_places_trigger_with_two_exits_oco_nested(
        self, place_order_client, account_hash, order_id
    ):
        ctx = make_ctx(place_order_client)

        entry: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 100,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        exits = [
            orders.OrderDesc(
                symbol="SPY",
                quantity=100,
                instruction="SELL",
                order_type="LIMIT",
                price=165.00,
            ),
            orders.OrderDesc(
                symbol="SPY",
                quantity=100,
                instruction="SELL",
                order_type="STOP",
                stop_price=140.00,
            ),
        ]

        result = run(orders.place_trigger_order(ctx, account_hash, entry, exits))

        assert result["orderId"] == order_id

        order_spec = place_order_client.captured["kwargs"]["order_spec"]
        assert order_spec["orderStrategyType"] == "TRIGGER"

        # Child should be an OCO wrapping two orders
        oco_child = order_spec["childOrderStrategies"][0]
        assert oco_child["orderStrategyType"] == "OCO"
        assert len(oco_child["childOrderStrategies"]) == 2

    def test_wrong_exit_count_raises(self, place_order_client, account_hash):
        ctx = make_ctx(place_order_client)

        entry: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        # 3 exits should raise ValueError
        exits = [
            orders.OrderDesc(
                symbol="SPY", quantity=10, instruction="SELL", order_type="MARKET"
            ),
            orders.OrderDesc(
                symbol="SPY", quantity=10, instruction="SELL", order_type="MARKET"
            ),
            orders.OrderDesc(
                symbol="SPY", quantity=10, instruction="SELL", order_type="MARKET"
            ),
        ]

        with pytest.raises(ValueError, match="exit_orders must contain 1 or 2 orders"):
            run(orders.place_trigger_order(ctx, account_hash, entry, exits))

    def test_invalid_entry_raises_with_prefix(self, place_order_client, account_hash):
        ctx = make_ctx(place_order_client)

        bad_entry: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "LIMIT",
            # price missing
        }
        exits = [
            orders.OrderDesc(
                symbol="SPY",
                quantity=10,
                instruction="SELL",
                order_type="MARKET",
            )
        ]

        with pytest.raises(ValueError, match="entry_order:"):
            run(orders.place_trigger_order(ctx, account_hash, bad_entry, exits))

    def test_invalid_exit_raises_with_index_prefix(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        entry: orders.OrderDesc = {
            "symbol": "SPY",
            "quantity": 10,
            "instruction": "BUY",
            "order_type": "MARKET",
        }
        exits = [
            orders.OrderDesc(
                symbol="SPY",
                quantity=10,
                instruction="SELL",
                order_type="LIMIT",
                # price missing
            )
        ]

        with pytest.raises(ValueError, match=r"exit_orders\[0\]:"):
            run(orders.place_trigger_order(ctx, account_hash, entry, exits))


class TestPlaceOptionComboOrder:
    @pytest.fixture
    def account_hash(self):
        return "combo_account_hash"

    @pytest.fixture
    def order_id(self):
        return 789789789

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    def test_places_vertical_spread(self, place_order_client, account_hash, order_id):
        ctx = make_ctx(place_order_client)

        legs = [
            {"instruction": "BUY_TO_OPEN", "symbol": "SPY 251219C500", "quantity": 1},
            {"instruction": "SELL_TO_OPEN", "symbol": "SPY 251219C510", "quantity": 1},
        ]

        result = run(
            orders.place_option_combo_order(
                ctx,
                account_hash,
                legs,
                "NET_DEBIT",
                price=2.50,
                complex_order_strategy_type="VERTICAL",
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]

        assert order_spec["orderStrategyType"] == "SINGLE"
        assert order_spec["orderType"] == "NET_DEBIT"
        assert order_spec["complexOrderStrategyType"] == "VERTICAL"
        assert len(order_spec["orderLegCollection"]) == 2

    def test_combo_order_requires_at_least_two_legs(
        self, place_order_client, account_hash
    ):
        ctx = make_ctx(place_order_client)

        single_leg = [
            {"instruction": "BUY_TO_OPEN", "symbol": "SPY 251219C500", "quantity": 1},
        ]

        with pytest.raises(ValueError, match="at least two option legs"):
            run(
                orders.place_option_combo_order(
                    ctx,
                    account_hash,
                    single_leg,
                    "NET_DEBIT",
                    price=2.50,
                )
            )

    def test_combo_order_empty_legs_raises(self, place_order_client, account_hash):
        ctx = make_ctx(place_order_client)

        with pytest.raises(ValueError, match="at least two option legs"):
            run(
                orders.place_option_combo_order(
                    ctx,
                    account_hash,
                    [],
                    "NET_DEBIT",
                    price=2.50,
                )
            )


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
