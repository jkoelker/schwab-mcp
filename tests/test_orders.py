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


class TestPlaceOneCancelsOtherOrder:
    @pytest.fixture
    def account_hash(self):
        return "oco_account_hash"

    @pytest.fixture
    def order_id(self):
        return 123123123

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    def test_places_oco_order_with_two_children(
        self, place_order_client, account_hash, order_id
    ):
        ctx = make_ctx(place_order_client)

        first_spec = run(
            orders.build_equity_order_spec("SPY", 100, "SELL", "LIMIT", price=160.00)
        )
        second_spec = run(
            orders.build_equity_order_spec(
                "SPY", 100, "SELL", "STOP", stop_price=140.00
            )
        )

        result = run(
            orders.place_one_cancels_other_order(
                ctx, account_hash, first_spec, second_spec
            )
        )

        assert result["orderId"] == order_id
        assert result["accountHash"] == account_hash

        captured = place_order_client.captured
        order_spec = captured["kwargs"]["order_spec"]

        assert order_spec["orderStrategyType"] == "OCO"
        assert len(order_spec["childOrderStrategies"]) == 2
        assert order_spec["childOrderStrategies"][0]["orderType"] == "LIMIT"
        assert order_spec["childOrderStrategies"][1]["orderType"] == "STOP"


class TestPlaceFirstTriggersSecondOrder:
    @pytest.fixture
    def account_hash(self):
        return "trigger_account_hash"

    @pytest.fixture
    def order_id(self):
        return 456456456

    @pytest.fixture
    def order_response(self, order_response_factory, account_hash, order_id):
        return order_response_factory(account_hash=account_hash, order_id=order_id)

    @pytest.fixture
    def place_order_client(self, place_order_client_factory, account_hash, order_id):
        return place_order_client_factory(account_hash=account_hash, order_id=order_id)

    def test_places_trigger_order_with_child(
        self, place_order_client, account_hash, order_id
    ):
        ctx = make_ctx(place_order_client)

        entry_spec = run(
            orders.build_equity_order_spec("SPY", 100, "BUY", "LIMIT", price=145.00)
        )
        exit_spec = run(
            orders.build_equity_order_spec("SPY", 100, "SELL", "LIMIT", price=160.00)
        )

        result = run(
            orders.place_first_triggers_second_order(
                ctx, account_hash, entry_spec, exit_spec
            )
        )

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
