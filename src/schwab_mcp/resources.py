from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

ORDER_STATUSES: dict[str, Any] = {
    "statuses": {
        "AWAITING_PARENT_ORDER": "Child order waiting for parent to execute",
        "AWAITING_CONDITION": "Order waiting for a condition to be met",
        "AWAITING_STOP_CONDITION": "Stop/trailing stop waiting for trigger price",
        "AWAITING_MANUAL_REVIEW": "Order requires manual review",
        "ACCEPTED": "Order accepted by the system",
        "AWAITING_UR_OUT": "Order awaiting UR out",
        "PENDING_ACTIVATION": "Order scheduled for future activation",
        "QUEUED": "Order queued for submission",
        "WORKING": "Order is active in the market",
        "REJECTED": "Order was rejected by exchange or broker",
        "PENDING_CANCEL": "Cancel request submitted, awaiting confirmation",
        "CANCELED": "Order was canceled",
        "PENDING_REPLACE": "Replace request submitted, awaiting confirmation",
        "REPLACED": "Order was replaced with a new order",
        "FILLED": "Order completely executed",
        "EXPIRED": "Order expired without filling",
        "NEW": "Order newly created",
        "AWAITING_RELEASE_TIME": "Order waiting for scheduled release time",
        "PENDING_ACKNOWLEDGEMENT": "Order pending acknowledgement",
        "PENDING_RECALL": "Order pending recall",
    },
    "common_queries": {
        "open_orders": ["WORKING", "PENDING_ACTIVATION", "AWAITING_STOP_CONDITION"],
        "trailing_stops": ["AWAITING_STOP_CONDITION"],
        "completed": ["FILLED", "CANCELED", "EXPIRED", "REJECTED"],
    },
    "tips": [
        "Use AWAITING_STOP_CONDITION (not WORKING) to find trailing stops",
        "Use tomorrow's date as to_date for today's orders",
        "WORKING status is for regular limit/stop orders actively in market",
    ],
}

ORDER_TYPES: dict[str, Any] = {
    "equity_orders": {
        "MARKET": {
            "description": "Execute immediately at current market price",
            "required": ["symbol", "quantity", "instruction"],
            "optional": ["session", "duration"],
            "price_required": False,
            "stop_price_required": False,
        },
        "LIMIT": {
            "description": "Execute at specified price or better",
            "required": ["symbol", "quantity", "instruction", "price"],
            "optional": ["session", "duration"],
            "price_required": True,
            "stop_price_required": False,
        },
        "STOP": {
            "description": "Trigger market order when stop price reached",
            "required": ["symbol", "quantity", "instruction", "stop_price"],
            "optional": ["session", "duration"],
            "price_required": False,
            "stop_price_required": True,
        },
        "STOP_LIMIT": {
            "description": "Trigger limit order when stop price reached",
            "required": ["symbol", "quantity", "instruction", "price", "stop_price"],
            "optional": ["session", "duration"],
            "price_required": True,
            "stop_price_required": True,
        },
        "TRAILING_STOP": {
            "description": "Stop price trails market price by offset",
            "required": ["symbol", "quantity", "instruction", "trail_offset"],
            "optional": ["trail_type", "session", "duration"],
            "tool": "place_equity_trailing_stop_order",
        },
    },
    "option_orders": {
        "MARKET": {
            "description": "Execute immediately at current market price",
            "required": ["symbol", "quantity", "instruction"],
            "instructions": [
                "BUY_TO_OPEN",
                "SELL_TO_OPEN",
                "BUY_TO_CLOSE",
                "SELL_TO_CLOSE",
            ],
            "price_required": False,
        },
        "LIMIT": {
            "description": "Execute at specified price or better",
            "required": ["symbol", "quantity", "instruction", "price"],
            "instructions": [
                "BUY_TO_OPEN",
                "SELL_TO_OPEN",
                "BUY_TO_CLOSE",
                "SELL_TO_CLOSE",
            ],
            "price_required": True,
        },
    },
    "complex_orders": {
        "OCO": {
            "description": "One Cancels Other - execution of one cancels the other",
            "use_case": "Take-profit and stop-loss pairs",
            "tool": "place_one_cancels_other_order",
        },
        "TRIGGER": {
            "description": "First Triggers Second - second order placed after first executes",
            "use_case": "Activate exit orders after entry fills",
            "tool": "place_first_triggers_second_order",
        },
        "BRACKET": {
            "description": "Entry + OCO take-profit/stop-loss",
            "use_case": "Complete trade with automatic risk management",
            "tool": "place_bracket_order",
        },
        "COMBO": {
            "description": "Multi-leg option order with net price",
            "use_case": "Spreads, iron condors, straddles",
            "tool": "place_option_combo_order",
        },
    },
    "instructions": {
        "equity": ["BUY", "SELL"],
        "option": ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"],
    },
}

OPTION_SYMBOLS: dict[str, Any] = {
    "format": "{UNDERLYING} {YYMMDD}{C|P}{STRIKE}",
    "components": {
        "underlying": "Stock/ETF symbol (e.g., SPY, AAPL)",
        "expiration": "YYMMDD format (e.g., 251121 = November 21, 2025)",
        "contract_type": "C for Call, P for Put",
        "strike": "Strike price (no decimals for whole numbers)",
    },
    "examples": [
        {
            "symbol": "SPY 251121C500",
            "meaning": "SPY November 21, 2025 $500 Call",
        },
        {
            "symbol": "AAPL 240315P150",
            "meaning": "AAPL March 15, 2024 $150 Put",
        },
        {
            "symbol": "TSLA 250117C250",
            "meaning": "TSLA January 17, 2025 $250 Call",
        },
    ],
    "tips": [
        "Use create_option_symbol() tool to construct symbols programmatically",
        "Use get_option_chain() to find valid option symbols for a stock",
        "Use get_option_expiration_chain() to see available expiration dates",
    ],
}

TRADING_SESSIONS: dict[str, Any] = {
    "sessions": {
        "NORMAL": {
            "description": "Regular market hours",
            "hours": "9:30 AM - 4:00 PM ET",
            "default": True,
        },
        "AM": {
            "description": "Pre-market session",
            "hours": "7:00 AM - 9:30 AM ET",
            "default": False,
        },
        "PM": {
            "description": "After-hours session",
            "hours": "4:00 PM - 8:00 PM ET",
            "default": False,
        },
        "SEAMLESS": {
            "description": "Extended hours (combines AM + NORMAL + PM)",
            "hours": "7:00 AM - 8:00 PM ET",
            "default": False,
        },
    },
    "durations": {
        "DAY": {
            "description": "Order expires at end of trading session",
            "default": True,
        },
        "GOOD_TILL_CANCEL": {
            "description": "Order remains active until filled or canceled",
            "max_days": 180,
            "default": False,
        },
        "FILL_OR_KILL": {
            "description": "Must fill immediately and completely, or cancel",
            "valid_for": ["LIMIT", "STOP_LIMIT"],
            "default": False,
        },
    },
    "tips": [
        "Extended hours have wider spreads and lower liquidity",
        "Not all securities trade in extended hours",
        "FILL_OR_KILL only works with LIMIT and STOP_LIMIT orders",
    ],
}


def register_resources(server: FastMCP) -> None:
    @server.resource("schwab://reference/order-statuses")
    def order_statuses_resource() -> dict:
        """Reference guide for order status values, their meanings, and common queries."""
        return ORDER_STATUSES

    @server.resource("schwab://reference/order-types")
    def order_types_resource() -> dict:
        """Reference for order types, required parameters, and complex order strategies."""
        return ORDER_TYPES

    @server.resource("schwab://reference/option-symbols")
    def option_symbols_resource() -> dict:
        """Reference for option symbol format, construction, and examples."""
        return OPTION_SYMBOLS

    @server.resource("schwab://reference/trading-sessions")
    def trading_sessions_resource() -> dict:
        """Reference for trading sessions, durations, and market hours."""
        return TRADING_SESSIONS


__all__ = [
    "ORDER_STATUSES",
    "ORDER_TYPES",
    "OPTION_SYMBOLS",
    "TRADING_SESSIONS",
    "register_resources",
]
