from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from schwab_mcp.resources import (
    ORDER_STATUSES,
    ORDER_TYPES,
    OPTION_SYMBOLS,
    TRADING_SESSIONS,
    register_resources,
)


class TestStaticReferenceData:
    def test_order_statuses_has_required_keys(self):
        assert "statuses" in ORDER_STATUSES
        assert "common_queries" in ORDER_STATUSES
        assert "tips" in ORDER_STATUSES

    def test_order_statuses_includes_trailing_stop_status(self):
        assert "AWAITING_STOP_CONDITION" in ORDER_STATUSES["statuses"]
        assert (
            "AWAITING_STOP_CONDITION"
            in ORDER_STATUSES["common_queries"]["trailing_stops"]
        )

    def test_order_types_has_equity_and_option_sections(self):
        assert "equity_orders" in ORDER_TYPES
        assert "option_orders" in ORDER_TYPES
        assert "complex_orders" in ORDER_TYPES
        assert "instructions" in ORDER_TYPES

    def test_order_types_includes_all_equity_types(self):
        equity = ORDER_TYPES["equity_orders"]
        for order_type in ["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAILING_STOP"]:
            assert order_type in equity

    def test_option_symbols_has_format_and_examples(self):
        assert "format" in OPTION_SYMBOLS
        assert "components" in OPTION_SYMBOLS
        assert "examples" in OPTION_SYMBOLS
        assert len(OPTION_SYMBOLS["examples"]) >= 2

    def test_trading_sessions_has_sessions_and_durations(self):
        assert "sessions" in TRADING_SESSIONS
        assert "durations" in TRADING_SESSIONS
        assert "NORMAL" in TRADING_SESSIONS["sessions"]
        assert "DAY" in TRADING_SESSIONS["durations"]


class TestRegisterResources:
    def test_registers_static_resources(self):
        import asyncio

        server = FastMCP(name="test")
        register_resources(server)

        resources = asyncio.run(server.list_resources())
        registered_uris = [str(r.uri) for r in resources]

        static_uris = [
            "schwab://reference/order-statuses",
            "schwab://reference/order-types",
            "schwab://reference/option-symbols",
            "schwab://reference/trading-sessions",
        ]
        for uri in static_uris:
            assert uri in registered_uris, f"Missing resource: {uri}"
