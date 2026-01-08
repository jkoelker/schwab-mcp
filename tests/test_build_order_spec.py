from typing import Any, cast

import pytest
from schwab_mcp.tools.orders import (
    _build_equity_order_spec,
    _build_option_order_spec,
    _build_trailing_stop_order_spec,
)


class TestBuildEquityOrderSpec:
    @pytest.fixture
    def symbol(self):
        return "AAPL"

    @pytest.fixture
    def quantity(self):
        return 10

    @pytest.mark.parametrize(
        "instruction",
        ["BUY", "SELL", "buy", "sell"],
    )
    def test_market_order_valid(self, symbol, quantity, instruction):
        result = _build_equity_order_spec(symbol, quantity, instruction, "MARKET")
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "MARKET"
        assert spec["orderLegCollection"][0]["instrument"]["symbol"] == symbol
        assert spec["orderLegCollection"][0]["quantity"] == quantity
        assert spec["orderLegCollection"][0]["instruction"] == instruction.upper()

    @pytest.mark.parametrize(
        "instruction",
        ["BUY", "SELL"],
    )
    def test_limit_order_valid(self, symbol, quantity, instruction):
        result = _build_equity_order_spec(
            symbol, quantity, instruction, "LIMIT", price=150.00
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "LIMIT"
        assert float(spec["price"]) == 150.00
        assert spec["orderLegCollection"][0]["instruction"] == instruction

    @pytest.mark.parametrize(
        "instruction",
        ["BUY", "SELL"],
    )
    def test_stop_order_valid(self, symbol, quantity, instruction):
        result = _build_equity_order_spec(
            symbol, quantity, instruction, "STOP", stop_price=145.00
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "STOP"
        assert float(spec["stopPrice"]) == 145.00
        assert spec["orderLegCollection"][0]["instruction"] == instruction

    @pytest.mark.parametrize(
        "instruction",
        ["BUY", "SELL"],
    )
    def test_stop_limit_order_valid(self, symbol, quantity, instruction):
        result = _build_equity_order_spec(
            symbol, quantity, instruction, "STOP_LIMIT", price=150.00, stop_price=145.00
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "STOP_LIMIT"
        assert float(spec["price"]) == 150.00
        assert float(spec["stopPrice"]) == 145.00
        assert spec["orderLegCollection"][0]["instruction"] == instruction

    def test_market_order_case_insensitive(self, symbol, quantity):
        result = _build_equity_order_spec(symbol, quantity, "buy", "market")
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "MARKET"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY"

    @pytest.mark.parametrize(
        ("order_type", "price", "stop_price", "expected_error"),
        [
            ("MARKET", 100.0, None, "MARKET orders should not include price"),
            ("MARKET", None, 100.0, "MARKET orders should not include stop_price"),
            ("MARKET", 100.0, 100.0, "MARKET orders should not include price"),
            ("LIMIT", None, None, "LIMIT orders require a price"),
            ("LIMIT", 100.0, 50.0, "LIMIT orders should not include stop_price"),
            ("STOP", None, None, "STOP orders require a stop_price"),
            ("STOP", 100.0, 50.0, "STOP orders should not include price"),
            ("STOP_LIMIT", None, 50.0, "STOP_LIMIT orders require a price"),
            ("STOP_LIMIT", 100.0, None, "STOP_LIMIT orders require a stop_price"),
        ],
    )
    def test_price_validation_errors(
        self, symbol, quantity, order_type, price, stop_price, expected_error
    ):
        with pytest.raises(ValueError, match=expected_error):
            _build_equity_order_spec(
                symbol, quantity, "BUY", order_type, price=price, stop_price=stop_price
            )

    def test_invalid_order_type(self, symbol, quantity):
        with pytest.raises(
            ValueError, match="Invalid order_type: TRAILING_STOP. Must be one of"
        ):
            _build_equity_order_spec(symbol, quantity, "BUY", "TRAILING_STOP")

    @pytest.mark.parametrize(
        "order_type",
        ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
    )
    def test_invalid_instruction(self, symbol, quantity, order_type):
        price = 100.0 if order_type in ("LIMIT", "STOP_LIMIT") else None
        stop_price = 95.0 if order_type in ("STOP", "STOP_LIMIT") else None

        with pytest.raises(
            ValueError, match=f"Invalid instruction for {order_type} order"
        ):
            _build_equity_order_spec(
                symbol,
                quantity,
                "HOLD",
                order_type,
                price=price,
                stop_price=stop_price,
            )


class TestBuildOptionOrderSpec:
    @pytest.fixture
    def symbol(self):
        return "SPY 251219C500"

    @pytest.fixture
    def quantity(self):
        return 5

    @pytest.mark.parametrize(
        "instruction",
        ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"],
    )
    def test_market_order_valid(self, symbol, quantity, instruction):
        result = _build_option_order_spec(symbol, quantity, instruction, "MARKET")
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "MARKET"
        assert spec["orderLegCollection"][0]["instrument"]["symbol"] == symbol
        assert spec["orderLegCollection"][0]["quantity"] == quantity
        assert spec["orderLegCollection"][0]["instruction"] == instruction

    @pytest.mark.parametrize(
        "instruction",
        ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"],
    )
    def test_limit_order_valid(self, symbol, quantity, instruction):
        result = _build_option_order_spec(
            symbol, quantity, instruction, "LIMIT", price=2.50
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "LIMIT"
        assert float(spec["price"]) == 2.50
        assert spec["orderLegCollection"][0]["instruction"] == instruction

    def test_case_insensitive(self, symbol, quantity):
        result = _build_option_order_spec(
            symbol, quantity, "buy_to_open", "limit", price=2.50
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "LIMIT"
        assert spec["orderLegCollection"][0]["instruction"] == "BUY_TO_OPEN"

    def test_market_order_with_price_raises(self, symbol, quantity):
        with pytest.raises(
            ValueError, match="MARKET orders should not include a price parameter"
        ):
            _build_option_order_spec(
                symbol, quantity, "BUY_TO_OPEN", "MARKET", price=2.50
            )

    def test_limit_order_without_price_raises(self, symbol, quantity):
        with pytest.raises(ValueError, match="LIMIT orders require a price parameter"):
            _build_option_order_spec(symbol, quantity, "BUY_TO_OPEN", "LIMIT")

    def test_invalid_order_type(self, symbol, quantity):
        with pytest.raises(
            ValueError, match="Invalid order_type: STOP. Must be one of"
        ):
            _build_option_order_spec(symbol, quantity, "BUY_TO_OPEN", "STOP")

    @pytest.mark.parametrize(
        "order_type",
        ["MARKET", "LIMIT"],
    )
    def test_invalid_instruction(self, symbol, quantity, order_type):
        price = 2.50 if order_type == "LIMIT" else None

        with pytest.raises(
            ValueError, match=f"Invalid instruction for {order_type} option order"
        ):
            _build_option_order_spec(symbol, quantity, "BUY", order_type, price=price)


class TestBuildTrailingStopOrderSpec:
    @pytest.fixture
    def symbol(self):
        return "AAPL"

    @pytest.fixture
    def quantity(self):
        return 10

    @pytest.mark.parametrize("instruction", ["BUY", "SELL", "buy", "sell"])
    def test_trailing_stop_value_valid(self, symbol, quantity, instruction):
        result = _build_trailing_stop_order_spec(
            symbol, quantity, instruction, trail_offset=5.0, trail_type="VALUE"
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "TRAILING_STOP"
        assert spec["stopPriceOffset"] == 5.0
        assert spec["stopPriceLinkType"] == "VALUE"
        assert spec["stopPriceLinkBasis"] == "LAST"
        assert spec["orderLegCollection"][0]["instrument"]["symbol"] == symbol
        assert spec["orderLegCollection"][0]["quantity"] == quantity
        assert spec["orderLegCollection"][0]["instruction"] == instruction.upper()

    @pytest.mark.parametrize("instruction", ["BUY", "SELL"])
    def test_trailing_stop_percent_valid(self, symbol, quantity, instruction):
        result = _build_trailing_stop_order_spec(
            symbol, quantity, instruction, trail_offset=5.0, trail_type="PERCENT"
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "TRAILING_STOP"
        assert spec["stopPriceOffset"] == 5.0
        assert spec["stopPriceLinkType"] == "PERCENT"
        assert spec["stopPriceLinkBasis"] == "LAST"

    def test_trailing_stop_case_insensitive(self, symbol, quantity):
        result = _build_trailing_stop_order_spec(
            symbol, quantity, "sell", trail_offset=10.0, trail_type="percent"
        )
        spec = cast(dict[str, Any], result.build())

        assert spec["orderType"] == "TRAILING_STOP"
        assert spec["stopPriceLinkType"] == "PERCENT"
        assert spec["orderLegCollection"][0]["instruction"] == "SELL"

    def test_invalid_instruction(self, symbol, quantity):
        with pytest.raises(ValueError, match="Invalid instruction: HOLD"):
            _build_trailing_stop_order_spec(symbol, quantity, "HOLD", trail_offset=5.0)

    def test_invalid_trail_type(self, symbol, quantity):
        with pytest.raises(ValueError, match="Invalid trail_type: TICK"):
            _build_trailing_stop_order_spec(
                symbol, quantity, "SELL", trail_offset=5.0, trail_type="TICK"
            )

    @pytest.mark.parametrize("bad_offset", [0, -1, -5.0])
    def test_invalid_trail_offset(self, symbol, quantity, bad_offset):
        with pytest.raises(ValueError, match="trail_offset must be positive"):
            _build_trailing_stop_order_spec(
                symbol, quantity, "SELL", trail_offset=bad_offset
            )
