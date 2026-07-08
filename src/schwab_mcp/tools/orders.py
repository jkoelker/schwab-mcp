#

from collections.abc import Callable
from typing import Annotated, Any, cast

from typing_extensions import TypedDict

from mcp.server.fastmcp import FastMCP
from schwab.utils import (
    AccountHashMismatchException,
    UnsuccessfulOrderException,
    Utils as SchwabUtils,
)
from schwab.orders.common import Duration
from schwab.orders.common import first_triggers_second as trigger_builder
from schwab.orders.common import one_cancels_other as oco_builder
from schwab.orders.options import OptionSymbol
from schwab.orders.generic import OrderBuilder

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import parse_date
from schwab_mcp.tools.order_helpers import (
    equity_buy_limit,
    equity_buy_market,
    equity_buy_stop,
    equity_buy_stop_limit,
    equity_sell_limit,
    equity_sell_market,
    equity_sell_stop,
    equity_sell_stop_limit,
    equity_trailing_stop,
    option_buy_to_close_limit,
    option_buy_to_close_market,
    option_buy_to_open_limit,
    option_buy_to_open_market,
    option_sell_to_close_limit,
    option_sell_to_close_market,
    option_sell_to_open_limit,
    option_sell_to_open_market,
)
from schwab_mcp.tools.utils import JSONType, ResponseHandler, call


_COMPACT_ORDER_TOP_FIELDS = frozenset(
    {
        "orderId",
        "status",
        "quantity",
        "filledQuantity",
        "remainingQuantity",
        "price",
        "stopPrice",
        "orderType",
        "session",
        "duration",
        "orderStrategyType",
        "enteredTime",
        "closeTime",
    }
)


def _order_legs_summary(order: dict[str, Any]) -> list[dict[str, Any]]:
    legs = order.get("orderLegCollection", [])
    result = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        instrument = leg.get("instrument")
        symbol = instrument.get("symbol") if isinstance(instrument, dict) else None
        result.append(
            {
                "symbol": symbol,
                "instruction": leg.get("instruction"),
                "quantity": leg.get("quantity"),
            }
        )
    return result


def _prune_order(order: JSONType) -> JSONType:
    if not isinstance(order, dict):
        return order
    result: dict[str, JSONType] = {
        k: v for k, v in order.items() if k in _COMPACT_ORDER_TOP_FIELDS
    }
    order_legs = order.get("orderLegCollection")
    if isinstance(order_legs, list) and order_legs:
        legs_summary = _order_legs_summary(order)
        if legs_summary:
            result["legs"] = legs_summary
    child_strategies = order.get("childOrderStrategies")
    if isinstance(child_strategies, list) and child_strategies:
        result["childOrderStrategies"] = [
            _prune_order(child) for child in child_strategies
        ]
    return result


def _prune_orders(payload: JSONType) -> JSONType:
    return (
        [_prune_order(o) for o in payload]
        if isinstance(payload, list)
        else _prune_order(payload)
    )


# Common shorthand aliases for schwab-py's Duration enum values. GTC is the
# most frequently used trading abbreviation and is not recognized by
# schwab-py itself; IOC/FOK are included as the same kind of well-known
# shorthand. There is no unambiguous shorthand for END_OF_WEEK/END_OF_MONTH/
# NEXT_END_OF_MONTH, so those are only accepted by their exact enum names.
_DURATION_ALIASES: dict[str, str] = {
    "GTC": "GOOD_TILL_CANCEL",
    "IOC": "IMMEDIATE_OR_CANCEL",
    "FOK": "FILL_OR_KILL",
}

# Derived from schwab-py's real Duration enum (rather than hardcoded) so this
# automatically tracks any values schwab-py adds in future releases.
_VALID_DURATIONS: frozenset[str] = frozenset(d.name for d in Duration)


def _normalize_duration(duration: str | Duration) -> str:
    """Resolve a duration string/alias to a canonical schwab-py Duration name.

    Accepts common shorthand (e.g. ``GTC``) in addition to the exact
    schwab-py enum names, case-insensitively. Also accepts a ``Duration``
    enum instance directly. Raises ``ValueError`` locally (before any Schwab
    API call) if the value isn't recognized.
    """
    if isinstance(duration, Duration):
        return duration.name
    if not isinstance(duration, str):
        raise ValueError(
            f"Invalid duration: {duration!r}. Must be a string or Duration enum value."
        )
    candidate = duration.strip().upper()
    candidate = _DURATION_ALIASES.get(candidate, candidate)

    if candidate not in _VALID_DURATIONS:
        raise ValueError(
            f"Invalid duration: {duration!r}. Must be one of: "
            f"{', '.join(sorted(_VALID_DURATIONS))} "
            f"(aliases accepted: {', '.join(sorted(_DURATION_ALIASES))})"
        )

    return candidate


# Internal helper function to apply session and duration settings
def _apply_order_settings(order_spec, session: str | None, duration: str | None):
    """Internal helper to apply session and duration to an order spec builder."""
    if session:
        order_spec = order_spec.set_session(session)
    if duration is not None:
        order_spec = order_spec.set_duration(_normalize_duration(duration))
    return order_spec


_EQUITY_ORDER_BUILDERS: dict[tuple[str, str], tuple[Any, bool, bool]] = {
    ("MARKET", "BUY"): (equity_buy_market, False, False),
    ("MARKET", "SELL"): (equity_sell_market, False, False),
    ("LIMIT", "BUY"): (equity_buy_limit, True, False),
    ("LIMIT", "SELL"): (equity_sell_limit, True, False),
    ("STOP", "BUY"): (equity_buy_stop, False, True),
    ("STOP", "SELL"): (equity_sell_stop, False, True),
    ("STOP_LIMIT", "BUY"): (equity_buy_stop_limit, True, True),
    ("STOP_LIMIT", "SELL"): (equity_sell_stop_limit, True, True),
}

_EQUITY_ORDER_TYPES = frozenset({"MARKET", "LIMIT", "STOP", "STOP_LIMIT"})
_EQUITY_INSTRUCTIONS = frozenset({"BUY", "SELL"})

_TRAILING_STOP_LINK_TYPES = frozenset({"VALUE", "PERCENT"})


def _build_equity_order_spec(
    symbol: str,
    quantity: int,
    instruction: str,
    order_type: str,
    price: float | None = None,
    stop_price: float | None = None,
):
    """Internal helper to build the core equity order spec builder based on parameters."""
    instruction = instruction.upper()
    order_type = order_type.upper()

    if order_type not in _EQUITY_ORDER_TYPES:
        raise ValueError(
            f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT, STOP, STOP_LIMIT"
        )

    if instruction not in _EQUITY_INSTRUCTIONS:
        raise ValueError(
            f"Invalid instruction for {order_type} order: {instruction}. Use BUY or SELL."
        )

    builder_func, needs_price, needs_stop_price = _EQUITY_ORDER_BUILDERS[
        (order_type, instruction)
    ]

    if needs_price and price is None:
        raise ValueError(f"{order_type} orders require a price")
    if not needs_price and price is not None:
        raise ValueError(f"{order_type} orders should not include price")
    if needs_stop_price and stop_price is None:
        raise ValueError(f"{order_type} orders require a stop_price")
    if not needs_stop_price and stop_price is not None:
        raise ValueError(f"{order_type} orders should not include stop_price")

    if needs_price and needs_stop_price:
        return builder_func(symbol, quantity, stop_price, price)
    elif needs_price:
        return builder_func(symbol, quantity, price)
    elif needs_stop_price:
        return builder_func(symbol, quantity, stop_price)
    else:
        return builder_func(symbol, quantity)


def _build_trailing_stop_order_spec(
    symbol: str,
    quantity: int,
    instruction: str,
    trail_offset: float,
    trail_type: str = "VALUE",
):
    instruction = instruction.upper()
    trail_type = trail_type.upper()

    if instruction not in _EQUITY_INSTRUCTIONS:
        raise ValueError(f"Invalid instruction: {instruction}. Must be BUY or SELL.")

    if trail_type not in _TRAILING_STOP_LINK_TYPES:
        raise ValueError(f"Invalid trail_type: {trail_type}. Must be VALUE or PERCENT.")

    if trail_offset <= 0:
        raise ValueError("trail_offset must be positive")

    return equity_trailing_stop(symbol, quantity, instruction, trail_offset, trail_type)


_OPTION_ORDER_BUILDERS: dict[str, tuple[Any, Any]] = {
    "BUY_TO_OPEN": (option_buy_to_open_market, option_buy_to_open_limit),
    "SELL_TO_OPEN": (option_sell_to_open_market, option_sell_to_open_limit),
    "BUY_TO_CLOSE": (option_buy_to_close_market, option_buy_to_close_limit),
    "SELL_TO_CLOSE": (option_sell_to_close_market, option_sell_to_close_limit),
}

_OPTION_ORDER_TYPES = frozenset({"MARKET", "LIMIT"})
_OPTION_INSTRUCTIONS = frozenset(_OPTION_ORDER_BUILDERS.keys())


def _build_option_order_spec(
    symbol: str,
    quantity: int,
    instruction: str,
    order_type: str,
    price: float | None = None,
):
    """Internal helper to build the core option order spec builder based on parameters."""
    instruction = instruction.upper()
    order_type = order_type.upper()

    if order_type not in _OPTION_ORDER_TYPES:
        raise ValueError(
            f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT"
        )

    if instruction not in _OPTION_INSTRUCTIONS:
        raise ValueError(
            f"Invalid instruction for {order_type} option order: {instruction}. "
            "Use BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, or SELL_TO_CLOSE."
        )

    market_builder, limit_builder = _OPTION_ORDER_BUILDERS[instruction]

    if order_type == "MARKET":
        if price is not None:
            raise ValueError("MARKET orders should not include a price parameter")
        return market_builder(symbol, quantity)
    else:
        if price is None:
            raise ValueError("LIMIT orders require a price parameter")
        return limit_builder(symbol, quantity, price)


class _OrderDescRequired(TypedDict):
    """Required fields for an order leg description."""

    symbol: str
    quantity: int
    instruction: str
    order_type: str


class OrderDesc(_OrderDescRequired, total=False):
    """Description of a single order leg for composite order tools.

    Required fields: symbol, quantity, instruction, order_type.
    Conditional fields depend on order_type:
      - price: required for LIMIT and STOP_LIMIT (equity/option)
      - stop_price: required for STOP and STOP_LIMIT (equity only)
      - trail_offset: required for TRAILING_STOP
      - trail_type: VALUE (default) or PERCENT for TRAILING_STOP
    Optional overrides: asset_type (EQUITY default), session, duration.
    """

    price: float
    stop_price: float
    trail_offset: float
    trail_type: str
    asset_type: str
    session: str
    duration: str


def _build_order_from_desc(
    desc: OrderDesc,
    default_session: str | None,
    default_duration: str | None,
) -> Any:
    """Build an OrderBuilder from an OrderDesc dict.

    Routes to the appropriate internal builder based on asset_type and
    order_type. Per-leg session/duration in the OrderDesc override the
    provided defaults when present.

    Raises ValueError with a descriptive message if required fields are
    missing or values are invalid. Since OrderDesc dicts typically originate
    from untrusted MCP tool-call JSON (not Python literals), required keys
    are checked explicitly at runtime rather than relying on static typing.
    """
    missing = [
        field
        for field in ("symbol", "quantity", "instruction", "order_type")
        if field not in desc
    ]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    symbol = desc["symbol"]
    if not isinstance(symbol, str):
        raise ValueError(f"symbol must be a string, got {symbol!r}")

    quantity = desc["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValueError(f"quantity must be an integer, got {quantity!r}")

    instruction = desc["instruction"]
    if not isinstance(instruction, str):
        raise ValueError(f"instruction must be a string, got {instruction!r}")

    raw_order_type = desc["order_type"]
    if not isinstance(raw_order_type, str):
        raise ValueError(f"order_type must be a string, got {raw_order_type!r}")
    order_type = raw_order_type.upper()

    raw_asset_type = desc.get("asset_type", "EQUITY")
    if not isinstance(raw_asset_type, str):
        raise ValueError(f"asset_type must be a string, got {raw_asset_type!r}")
    asset_type = raw_asset_type.upper()
    if asset_type not in ("EQUITY", "OPTION"):
        raise ValueError(f"Invalid asset_type: {asset_type}. Must be EQUITY or OPTION.")

    # Determine effective session/duration (per-leg overrides defaults)
    session = desc.get("session", default_session)
    duration = desc.get("duration", default_duration)

    if order_type == "TRAILING_STOP":
        if asset_type == "OPTION":
            raise ValueError(
                "TRAILING_STOP orders are not supported for OPTION asset_type"
            )
        trail_offset = desc.get("trail_offset")
        if trail_offset is None:
            raise ValueError("TRAILING_STOP orders require 'trail_offset'")
        trail_type = desc.get("trail_type", "VALUE")
        builder = _build_trailing_stop_order_spec(
            symbol, quantity, instruction, trail_offset, trail_type
        )
    elif asset_type == "OPTION":
        builder = _build_option_order_spec(
            symbol,
            quantity,
            instruction,
            order_type,
            price=desc.get("price"),
        )
    else:
        # Default: EQUITY
        builder = _build_equity_order_spec(
            symbol,
            quantity,
            instruction,
            order_type,
            price=desc.get("price"),
            stop_price=desc.get("stop_price"),
        )

    builder = _apply_order_settings(builder, session, duration)
    return builder


def _order_response_handler(ctx: SchwabContext, account_hash: str) -> ResponseHandler:
    utils = SchwabUtils(ctx.client, account_hash)

    def handler(response: Any) -> tuple[bool, JSONType]:
        headers = getattr(response, "headers", {})
        location = headers.get("Location") if headers else None

        try:
            order_id = utils.extract_order_id(response)
        except (AccountHashMismatchException, UnsuccessfulOrderException):
            order_id = None

        if order_id is None and location is None:
            return False, None

        payload: dict[str, Any] = {}
        if order_id is not None:
            payload["orderId"] = order_id
            payload["accountHash"] = account_hash
        if location is not None:
            payload["location"] = location

        return True, payload

    return handler


async def get_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to get details for"],
    verbose: Annotated[
        bool,
        "Return the full raw order payload (routing metadata, full nested child orders, execution activity) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns details for a specific order. By default returns compact fields only
    (orderId, status, quantity, filledQuantity, remainingQuantity, price, stopPrice,
    orderType, session, duration, orderStrategyType, enteredTime, closeTime, legs
    summary, and recursively-pruned childOrderStrategies); pass verbose=True for
    the full raw payload. Params: account_hash, order_id.
    """
    client = ctx.orders
    result = await call(client.get_order, order_id=order_id, account_hash=account_hash)
    return result if verbose else _prune_order(result)


async def get_orders(
    ctx: SchwabContext,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_accounts)"
    ],
    max_results: Annotated[int | None, "Maximum number of orders to return"] = None,
    from_date: Annotated[
        str | None,
        "Start date for orders ('YYYY-MM-DD', max 60 days past)",
    ] = None,
    to_date: Annotated[str | None, "End date for orders ('YYYY-MM-DD')"] = None,
    status: Annotated[
        list[str] | str | None,
        "Filter by order status (e.g., WORKING, FILLED, CANCELED). See full list below.",
    ] = None,
    verbose: Annotated[
        bool,
        "Return the full raw order payload (routing metadata, full nested child orders, execution activity) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns order history for an account. By default returns compact fields only
    (orderId, status, quantity, filledQuantity, remainingQuantity, price, stopPrice,
    orderType, session, duration, orderStrategyType, enteredTime, closeTime, legs
    summary, and recursively-pruned childOrderStrategies); pass verbose=True for
    the full raw payload. Filter by date range (max 60 days past) and status.
    Params: account_hash, max_results, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD), status (list/str).
    Status options: AWAITING_PARENT_ORDER, AWAITING_CONDITION, AWAITING_STOP_CONDITION, AWAITING_MANUAL_REVIEW, ACCEPTED, AWAITING_UR_OUT, PENDING_ACTIVATION, QUEUED, WORKING, REJECTED, PENDING_CANCEL, CANCELED, PENDING_REPLACE, REPLACED, FILLED, EXPIRED, NEW, AWAITING_RELEASE_TIME, PENDING_ACKNOWLEDGEMENT, PENDING_RECALL.
    Use tomorrow's date as to_date for today's orders. Use WORKING/PENDING_ACTIVATION for open orders.
    """
    client = ctx.orders

    from_date_obj = parse_date(from_date)
    to_date_obj = parse_date(to_date)

    kwargs: dict[str, Any] = {
        "max_results": max_results,
        "from_entered_datetime": from_date_obj,
        "to_entered_datetime": to_date_obj,
    }

    if status:
        if isinstance(status, str):
            # Single status: direct API call
            kwargs["status"] = client.Order.Status[status.upper()]
            result: JSONType = await call(
                client.get_orders_for_account,
                account_hash,
                **kwargs,
            )
        else:
            # Multiple statuses: make separate calls and merge results
            # The underlying schwab-py API only supports single status queries
            all_orders: list[Any] = []
            seen_order_ids: set[str] = set()
            for s in status:
                kwargs["status"] = client.Order.Status[s.upper()]
                partial = await call(
                    client.get_orders_for_account,
                    account_hash,
                    **kwargs,
                )
                if partial:
                    for order in cast(list[Any], partial):
                        order_id = str(order.get("orderId", ""))
                        if order_id and order_id not in seen_order_ids:
                            seen_order_ids.add(order_id)
                            all_orders.append(order)
            result = all_orders if all_orders else []
    else:
        result = await call(
            client.get_orders_for_account,
            account_hash,
            **kwargs,
        )

    return result if verbose else _prune_orders(result)


async def cancel_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to cancel"],
) -> JSONType:
    """
    Cancels a pending order. Cannot cancel executed/terminal orders. Params: account_hash, order_id. Returns cancellation request confirmation; check status after. *Write operation.*
    """
    client = ctx.orders
    return await call(client.cancel_order, order_id=order_id, account_hash=account_hash)


async def place_equity_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[str, "Stock symbol to trade"],
    quantity: Annotated[int, "Number of shares to trade"],
    instruction: Annotated[str, "BUY or SELL"],
    order_type: Annotated[str, "Order type: MARKET, LIMIT, STOP, or STOP_LIMIT"],
    price: Annotated[
        float | None, "Required for LIMIT; Limit price for STOP_LIMIT"
    ] = None,
    stop_price: Annotated[float | None, "Required for STOP and STOP_LIMIT"] = None,
    session: Annotated[
        str | None, "Trading session: NORMAL (default), AM, PM, or SEAMLESS"
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Order duration: DAY (default), GOOD_TILL_CANCEL (alias: GTC), IMMEDIATE_OR_CANCEL (alias: IOC), FILL_OR_KILL (alias: FOK; Limit/StopLimit only). Invalid values raise ValueError locally.",
    ] = "DAY",
) -> JSONType:
    """
    Places a single equity order (MARKET, LIMIT, STOP, STOP_LIMIT).
    Params: account_hash, symbol, quantity, instruction (BUY/SELL), order_type.
    Optional/Conditional: price (for LIMIT/STOP_LIMIT), stop_price (for STOP/STOP_LIMIT), session (default NORMAL), duration (default DAY).
    Note: FILL_OR_KILL duration is only valid for LIMIT and STOP_LIMIT orders.
    *Write operation.*
    """
    # Build the core order specification builder
    client = ctx.orders

    order_spec_builder = _build_equity_order_spec(
        symbol, quantity, instruction, order_type, price, stop_price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build the final order dictionary
    order_spec_dict = cast(dict[str, Any], order_spec_builder.build())

    # Place the order
    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=order_spec_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def place_option_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[str, "Option symbol (e.g., 'SPY_230616C400')"],
    quantity: Annotated[int, "Number of contracts to trade"],
    instruction: Annotated[
        str, "BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, or SELL_TO_CLOSE"
    ],
    order_type: Annotated[str, "Order type: MARKET or LIMIT"],
    price: Annotated[
        float | None, "Required for LIMIT orders (price per contract)"
    ] = None,
    session: Annotated[
        str | None, "Trading session: NORMAL (default), AM, PM, or SEAMLESS"
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Order duration: DAY (default), GOOD_TILL_CANCEL (alias: GTC), IMMEDIATE_OR_CANCEL (alias: IOC), FILL_OR_KILL (alias: FOK; Limit only). Invalid values raise ValueError locally.",
    ] = "DAY",
) -> JSONType:
    """
    Places a single option order (MARKET, LIMIT).
    Params: account_hash, symbol, quantity, instruction (BUY_TO_OPEN/etc.), order_type.
    Optional/Conditional: price (for LIMIT), session (default NORMAL), duration (default DAY).
    Note: FILL_OR_KILL duration is only valid for LIMIT orders.
    *Write operation.*
    """
    # Build the core order specification builder
    client = ctx.orders

    order_spec_builder = _build_option_order_spec(
        symbol, quantity, instruction, order_type, price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build the final order dictionary
    order_spec_dict = cast(dict[str, Any], order_spec_builder.build())

    # Place the order
    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=order_spec_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def place_equity_trailing_stop_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[str, "Stock symbol to trade"],
    quantity: Annotated[int, "Number of shares to trade"],
    instruction: Annotated[str, "BUY or SELL"],
    trail_offset: Annotated[
        float,
        "Trailing amount: dollar value if trail_type=VALUE, percentage if trail_type=PERCENT",
    ],
    trail_type: Annotated[
        str | None,
        "How to measure the trail: VALUE (dollars, default) or PERCENT",
    ] = "VALUE",
    session: Annotated[
        str | None, "Trading session: NORMAL (default), AM, PM, or SEAMLESS"
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Order duration: DAY (default), GOOD_TILL_CANCEL (alias: GTC), or IMMEDIATE_OR_CANCEL (alias: IOC). Invalid values raise ValueError locally.",
    ] = "DAY",
) -> JSONType:
    """
    Places a trailing stop order. Stop price adjusts as price moves favorably, tracking LAST price.
    Params: account_hash, symbol, quantity, instruction (BUY/SELL), trail_offset.
    Defaults: trail_type=VALUE (dollars), session=NORMAL, duration=DAY.
    Example: SELL 100 shares with $5 trailing stop triggers market sell if price drops $5 from high.
    *Write operation.*
    """
    client = ctx.orders

    order_spec_builder = _build_trailing_stop_order_spec(
        symbol,
        quantity,
        instruction,
        trail_offset,
        trail_type or "VALUE",
    )

    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)
    order_spec_dict = cast(dict[str, Any], order_spec_builder.build())

    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=order_spec_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def place_oco_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    first_order: Annotated[
        OrderDesc,
        "First order leg description. Required fields: symbol, quantity, instruction, order_type. "
        "Conditional: price (LIMIT/STOP_LIMIT), stop_price (STOP/STOP_LIMIT), "
        "trail_offset (TRAILING_STOP). Optional: asset_type (EQUITY/OPTION), session, duration.",
    ],
    second_order: Annotated[
        OrderDesc,
        "Second order leg description. Same fields as first_order. "
        "Execution of one cancels the other.",
    ],
    session: Annotated[
        str | None,
        "Default trading session for both legs: NORMAL (default), AM, PM, or SEAMLESS. Per-leg session in OrderDesc overrides this.",
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Default order duration for both legs: DAY (default), GOOD_TILL_CANCEL (alias: GTC), IMMEDIATE_OR_CANCEL (alias: IOC). Per-leg duration in OrderDesc overrides this.",
    ] = "DAY",
) -> JSONType:
    """
    Creates an OCO (One Cancels Other) order: execution of one cancels the other.
    Use for take-profit/stop-loss pairs on an existing position.

    Each order is described as an OrderDesc dict with fields:
      - symbol (str, required)
      - quantity (int, required)
      - instruction (str, required): BUY/SELL for equity; BUY_TO_OPEN/SELL_TO_OPEN/BUY_TO_CLOSE/SELL_TO_CLOSE for options
      - order_type (str, required): MARKET/LIMIT/STOP/STOP_LIMIT/TRAILING_STOP
      - price (float): required for LIMIT and STOP_LIMIT
      - stop_price (float): required for STOP and STOP_LIMIT (equity only)
      - trail_offset (float): required for TRAILING_STOP
      - trail_type (str): VALUE (default) or PERCENT for TRAILING_STOP
      - asset_type (str): EQUITY (default) or OPTION
      - session (str): per-leg override for session
      - duration (str): per-leg override for duration

    Params: account_hash, first_order (OrderDesc), second_order (OrderDesc).
    Optional: session (default NORMAL), duration (default DAY) — per-leg overrides these.
    *Write operation.*
    """
    client = ctx.orders

    try:
        first_builder = _build_order_from_desc(first_order, session, duration)
    except ValueError as exc:
        raise ValueError(f"first_order: {exc}") from exc

    try:
        second_builder = _build_order_from_desc(second_order, session, duration)
    except ValueError as exc:
        raise ValueError(f"second_order: {exc}") from exc

    oco_order_builder = oco_builder(first_builder, second_builder)
    order_spec_dict = cast(dict[str, Any], oco_order_builder.build())

    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=order_spec_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def place_trigger_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    entry_order: Annotated[
        OrderDesc,
        "Entry (primary) order description. Required fields: symbol, quantity, instruction, order_type. "
        "Conditional: price (LIMIT/STOP_LIMIT), stop_price (STOP/STOP_LIMIT), "
        "trail_offset (TRAILING_STOP). Optional: asset_type (EQUITY/OPTION), session, duration.",
    ],
    exit_orders: Annotated[
        list[OrderDesc],
        "Exit order(s) triggered after entry fills. "
        "1 exit: simple trigger(entry, exit). "
        "2 exits: trigger(entry, oco(exit1, exit2)) — full bracket-like structure. "
        "Any other count raises ValueError.",
    ],
    session: Annotated[
        str | None,
        "Default trading session for all legs: NORMAL (default), AM, PM, or SEAMLESS. Per-leg session in OrderDesc overrides this.",
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Default order duration for all legs: DAY (default), GOOD_TILL_CANCEL (alias: GTC), IMMEDIATE_OR_CANCEL (alias: IOC). Per-leg duration in OrderDesc overrides this.",
    ] = "DAY",
) -> JSONType:
    """
    Creates a conditional (trigger) order: exit order(s) are placed only after the entry executes.

    Each order is described as an OrderDesc dict with fields:
      - symbol (str, required)
      - quantity (int, required)
      - instruction (str, required): BUY/SELL for equity; BUY_TO_OPEN/SELL_TO_OPEN/BUY_TO_CLOSE/SELL_TO_CLOSE for options
      - order_type (str, required): MARKET/LIMIT/STOP/STOP_LIMIT/TRAILING_STOP
      - price (float): required for LIMIT and STOP_LIMIT
      - stop_price (float): required for STOP and STOP_LIMIT (equity only)
      - trail_offset (float): required for TRAILING_STOP
      - trail_type (str): VALUE (default) or PERCENT for TRAILING_STOP
      - asset_type (str): EQUITY (default) or OPTION
      - session (str): per-leg override for session
      - duration (str): per-leg override for duration

    exit_orders must contain 1 or 2 items:
      - 1 exit: TRIGGER > SINGLE(exit)
      - 2 exits: TRIGGER > OCO(exit1, exit2)

    Params: account_hash, entry_order (OrderDesc), exit_orders (list of 1-2 OrderDesc).
    Optional: session (default NORMAL), duration (default DAY) — per-leg overrides these.
    *Write operation.*
    """
    if len(exit_orders) not in (1, 2):
        raise ValueError("exit_orders must contain 1 or 2 orders")

    client = ctx.orders

    try:
        entry_builder = _build_order_from_desc(entry_order, session, duration)
    except ValueError as exc:
        raise ValueError(f"entry_order: {exc}") from exc

    exit_builders = []
    for i, exit_desc in enumerate(exit_orders):
        try:
            exit_builders.append(_build_order_from_desc(exit_desc, session, duration))
        except ValueError as exc:
            raise ValueError(f"exit_orders[{i}]: {exc}") from exc

    if len(exit_builders) == 1:
        trigger_order_builder = trigger_builder(entry_builder, exit_builders[0])
    else:
        oco_exit = oco_builder(exit_builders[0], exit_builders[1])
        trigger_order_builder = trigger_builder(entry_builder, oco_exit)

    order_spec_dict = cast(dict[str, Any], trigger_order_builder.build())

    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=order_spec_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def create_option_symbol(
    underlying_symbol: Annotated[
        str, "Symbol of the underlying security (e.g., 'SPY', 'AAPL')"
    ],
    expiration_date: Annotated[
        str, "Expiration date in YYMMDD format (e.g., '230616')"
    ],
    contract_type: Annotated[
        str, "Contract type: 'C' or 'CALL' for calls, 'P' or 'PUT' for puts"
    ],
    strike_price: Annotated[str, "Strike price as a string (e.g., '400', '150.5')"],
) -> str:
    """
    Creates formatted option symbol string from components (e.g., 'SPY 230616C400').
    Params: underlying_symbol, expiration_date (YYMMDD), contract_type (C/CALL or P/PUT), strike_price (string).
    Does not validate market existence. Use get_option_chain() to find valid options.
    """
    # The OptionSymbol helper expects YYMMDD format directly.
    option_symbol = OptionSymbol(
        underlying_symbol, expiration_date, contract_type, strike_price
    )
    return option_symbol.build()


async def place_bracket_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[str, "Stock symbol to trade"],
    quantity: Annotated[int, "Number of shares to trade"],
    entry_instruction: Annotated[str, "BUY or SELL for the entry order"],
    entry_type: Annotated[str, "Entry order type: MARKET, LIMIT, STOP, or STOP_LIMIT"],
    profit_price: Annotated[
        float | None, "Take-profit limit price (optional if loss_price provided)"
    ] = None,
    loss_price: Annotated[
        float | None, "Stop-loss trigger price (optional if profit_price provided)"
    ] = None,
    entry_price: Annotated[
        float | None, "Required for LIMIT entry; Limit price for STOP_LIMIT entry"
    ] = None,
    entry_stop_price: Annotated[
        float | None, "Required for STOP and STOP_LIMIT entry orders"
    ] = None,
    session: Annotated[
        str | None,
        "Trading session for all legs: NORMAL (default), AM, PM, or SEAMLESS",
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Order duration for all legs: DAY (default), GOOD_TILL_CANCEL (alias: GTC), or IMMEDIATE_OR_CANCEL (alias: IOC). Invalid values raise ValueError locally.",
    ] = "DAY",
    exit_session: Annotated[
        str | None,
        "Trading session override for exit legs only (take-profit/stop-loss). Defaults to session when not provided. Useful for GTC exits with a DAY entry.",
    ] = None,
    exit_duration: Annotated[
        str | None,
        "Duration override for exit legs only (take-profit/stop-loss). Defaults to duration when not provided. Common pattern: entry DAY + exits GOOD_TILL_CANCEL.",
    ] = None,
) -> JSONType:
    """
    Creates a bracket order: entry + exit leg(s) that trigger after entry executes.

    Exit behavior depends on which prices are provided:
    - Both profit_price and loss_price: TRIGGER > OCO(limit, stop) — full bracket with take-profit and stop-loss.
    - Only loss_price: TRIGGER > SINGLE(stop) — stop-loss only, no take-profit leg.
    - Only profit_price: TRIGGER > SINGLE(limit) — take-profit only, no stop-loss leg.
    - Neither: raises ValueError before any order is submitted.

    Params: account_hash, symbol, quantity, entry_instruction (BUY/SELL), entry_type (MARKET/LIMIT/STOP/STOP_LIMIT), profit_price, loss_price.
    At least one of profit_price or loss_price must be provided.
    Optional/Conditional: entry_price (for LIMIT/STOP_LIMIT), entry_stop_price (for STOP/STOP_LIMIT), session (default NORMAL), duration (default DAY).
    Optional: exit_session and exit_duration override session/duration for the exit legs only (e.g., entry DAY + exits GOOD_TILL_CANCEL).
    Ensure profit/loss prices are correctly positioned relative to entry (e.g., profit > entry for BUY).
    Note: FILL_OR_KILL is not typically used with bracket orders.
    *Write operation.*
    """
    # Validate that at least one exit price is provided
    if profit_price is None and loss_price is None:
        raise ValueError("At least one of profit_price or loss_price must be provided")

    # Validate entry instruction
    client = ctx.orders

    entry_instruction = entry_instruction.upper()
    if entry_instruction not in ["BUY", "SELL"]:
        raise ValueError(
            f"Invalid entry_instruction: {entry_instruction}. Use BUY or SELL."
        )

    # Determine exit instructions (opposite of entry)
    exit_instruction = "SELL" if entry_instruction == "BUY" else "BUY"

    # Effective exit session/duration fall back to entry-level values when not specified
    eff_exit_session = exit_session if exit_session is not None else session
    eff_exit_duration = exit_duration if exit_duration is not None else duration

    # Create entry order spec builder using the internal helper
    entry_order_builder = _build_equity_order_spec(
        symbol,
        quantity,
        entry_instruction,
        entry_type,
        price=entry_price,
        stop_price=entry_stop_price,
    )
    # Apply settings to entry order builder
    entry_order_builder = _apply_order_settings(entry_order_builder, session, duration)

    # Build exit leg(s) based on which prices are provided
    if profit_price is not None:
        # Create take-profit (limit) order spec builder
        if exit_instruction == "BUY":
            profit_order_builder = equity_buy_limit(symbol, quantity, profit_price)
        else:  # SELL
            profit_order_builder = equity_sell_limit(symbol, quantity, profit_price)
        profit_order_builder = _apply_order_settings(
            profit_order_builder, eff_exit_session, eff_exit_duration
        )

    if loss_price is not None:
        # Create stop-loss (stop) order spec builder
        if exit_instruction == "BUY":
            loss_order_builder = equity_buy_stop(symbol, quantity, loss_price)
        else:  # SELL
            loss_order_builder = equity_sell_stop(symbol, quantity, loss_price)
        loss_order_builder = _apply_order_settings(
            loss_order_builder, eff_exit_session, eff_exit_duration
        )

    if profit_price is not None and loss_price is not None:
        # Both prices: entry triggers OCO(profit, loss)
        oco_exit_order_builder = oco_builder(profit_order_builder, loss_order_builder)
        bracket_order_builder = trigger_builder(
            entry_order_builder, oco_exit_order_builder
        )
    elif loss_price is not None:
        # Stop-loss only: entry triggers single stop order
        bracket_order_builder = trigger_builder(entry_order_builder, loss_order_builder)
    else:
        # Take-profit only: entry triggers single limit order
        bracket_order_builder = trigger_builder(
            entry_order_builder, profit_order_builder
        )

    # Build the final complex bracket order dictionary
    bracket_order_dict = cast(dict[str, Any], bracket_order_builder.build())

    # Place the complex bracket order
    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=bracket_order_dict,
        response_handler=_order_response_handler(ctx, account_hash),
    )


async def place_option_combo_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    legs: Annotated[
        list[dict[str, Any]],
        "List of option legs. Each leg requires: 'symbol' (str), 'quantity' (int), 'instruction' (BUY_TO_OPEN/SELL_TO_OPEN/BUY_TO_CLOSE/SELL_TO_CLOSE).",
    ],
    order_type: Annotated[
        str, "Combo order type: NET_CREDIT, NET_DEBIT, NET_ZERO, or MARKET"
    ],
    price: Annotated[
        float | None,
        "Net price for the combo (required for NET_CREDIT/NET_DEBIT; omit for MARKET/NET_ZERO).",
    ] = None,
    session: Annotated[
        str | None, "Trading session: NORMAL (default), AM, PM, or SEAMLESS"
    ] = "NORMAL",
    duration: Annotated[
        str | None,
        "Order duration: DAY (default), GOOD_TILL_CANCEL (alias: GTC), or IMMEDIATE_OR_CANCEL (alias: IOC). Invalid values raise ValueError locally.",
    ] = "DAY",
    complex_order_strategy_type: Annotated[
        str | None,
        "Optional complex type: IRON_CONDOR, VERTICAL, CALENDAR, CUSTOM, etc. Defaults to CUSTOM.",
    ] = "CUSTOM",
) -> JSONType:
    """
    Places a single multi-leg option order (combo/spread) with a net price.

    - Submit multiple option legs in one order payload using a single net
      price for LIMIT orders.
    - Each leg must include: instruction, symbol, quantity.
    - Example legs item: {"instruction": "SELL_TO_OPEN", "symbol": "SPY 251121C500", "quantity": 1}

    Notes:
    - LIMIT is recommended for combos; MARKET support may vary by account/venue.
    - The API infers debit/credit from leg directions; pass a positive price.
    *Write operation.*
    """
    if not legs or len(legs) < 2:
        raise ValueError("Provide at least two option legs for a combo order")

    # Build a single order with multiple option legs
    builder = OrderBuilder(enforce_enums=False).set_order_strategy_type("SINGLE")

    # Apply session/duration consistently with other tools
    builder = _apply_order_settings(builder, session, duration)

    # complex order type helps the API validate multi-leg intent
    if complex_order_strategy_type:
        builder = builder.set_complex_order_strategy_type(
            complex_order_strategy_type.upper()
        )

    # Set order type and net price
    builder = builder.set_order_type(order_type.upper())
    if price is not None:
        builder = builder.set_price(price)  # net debit/credit as positive number

    for leg in legs:
        builder = builder.add_option_leg(
            leg["instruction"],
            leg["symbol"],
            leg["quantity"],
        )

    return await call(
        ctx.orders.place_order,
        account_hash=account_hash,
        order_spec=builder.build(),
        response_handler=_order_response_handler(ctx, account_hash),
    )


_READ_ONLY_TOOLS = (
    get_order,
    get_orders,
    create_option_symbol,
)

_WRITE_TOOLS = (
    cancel_order,
    place_equity_order,
    place_option_order,
    place_equity_trailing_stop_order,
    place_oco_order,
    place_trigger_order,
    place_bracket_order,
    place_option_combo_order,
)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)

    if not allow_write:
        return

    for func in _WRITE_TOOLS:
        register_tool(server, func, write=True, result_transform=result_transform)
