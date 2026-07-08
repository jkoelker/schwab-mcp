#

import uuid
from collections.abc import Callable
from typing import Annotated, Any, cast

from typing_extensions import TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
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

from schwab_mcp.approvals import ApprovalDecision, ApprovalRequest
from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool, run_approval
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
from schwab_mcp.tools.utils import JSONType, ResponseHandler, SchwabAPIError, call


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
_BRACKET_LOSS_TYPES = frozenset({"STOP", "STOP_LIMIT", "LIMIT"})
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
    _validate_equity_order_prices(
        order_type, needs_price, needs_stop_price, price, stop_price
    )

    args: list[Any] = [symbol, quantity]
    if needs_stop_price:
        args.append(stop_price)
    if needs_price:
        args.append(price)
    return builder_func(*args)


def _validate_equity_order_prices(
    order_type: str,
    needs_price: bool,
    needs_stop_price: bool,
    price: float | None,
    stop_price: float | None,
) -> None:
    """Validate that price/stop_price are supplied exactly when the order type
    requires them, raising ValueError otherwise."""
    if needs_price and price is None:
        raise ValueError(f"{order_type} orders require a price")
    if not needs_price and price is not None:
        raise ValueError(f"{order_type} orders should not include price")
    if needs_stop_price and stop_price is None:
        raise ValueError(f"{order_type} orders require a stop_price")
    if not needs_stop_price and stop_price is not None:
        raise ValueError(f"{order_type} orders should not include stop_price")


def _build_trailing_stop_from_desc(
    desc: "OrderDesc",
    symbol: str,
    quantity: int,
    instruction: str,
    asset_type: str,
) -> Any:
    """Extract and build a TRAILING_STOP order from an OrderDesc, raising the same
    ValueErrors as the inline branch it replaces."""
    if asset_type == "OPTION":
        raise ValueError("TRAILING_STOP orders are not supported for OPTION asset_type")
    trail_offset = desc.get("trail_offset")
    if trail_offset is None:
        raise ValueError("TRAILING_STOP orders require 'trail_offset'")
    trail_type = desc.get("trail_type", "VALUE")
    return _build_trailing_stop_order_spec(
        symbol, quantity, instruction, trail_offset, trail_type
    )


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


def _validate_order_desc_fields(desc: OrderDesc) -> tuple[str, int, str, str, str]:
    """Validate and extract the required OrderDesc fields, raising ValueError with
    a descriptive message if required fields are missing or values are invalid.

    Since OrderDesc dicts typically originate from untrusted MCP tool-call JSON
    (not Python literals), required keys are checked explicitly at runtime
    rather than relying on static typing.
    """
    required = ("symbol", "quantity", "instruction", "order_type")
    missing = [field for field in required if field not in desc]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    for field in ("symbol", "instruction", "order_type"):
        value = desc[field]
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string, got {value!r}")

    quantity = desc["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValueError(f"quantity must be an integer, got {quantity!r}")

    symbol = desc["symbol"]
    instruction = desc["instruction"]
    order_type = desc["order_type"].upper()
    asset_type = _validate_order_desc_asset_type(desc.get("asset_type", "EQUITY"))

    return symbol, quantity, instruction, order_type, asset_type


def _validate_order_desc_asset_type(raw_asset_type: Any) -> str:
    """Validate and normalize the OrderDesc asset_type field."""
    if not isinstance(raw_asset_type, str):
        raise ValueError(f"asset_type must be a string, got {raw_asset_type!r}")
    asset_type = raw_asset_type.upper()
    if asset_type not in ("EQUITY", "OPTION"):
        raise ValueError(f"Invalid asset_type: {asset_type}. Must be EQUITY or OPTION.")
    return asset_type


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
    symbol, quantity, instruction, order_type, asset_type = _validate_order_desc_fields(
        desc
    )

    # Determine effective session/duration (per-leg overrides defaults)
    session = desc.get("session", default_session)
    duration = desc.get("duration", default_duration)

    if order_type == "TRAILING_STOP":
        builder = _build_trailing_stop_from_desc(
            desc, symbol, quantity, instruction, asset_type
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


# ---------------------------------------------------------------------------
# _prepare_* helpers — pure spec builders, no ctx/API calls.
# Each extracts the build logic from the corresponding place_* tool so that
# preview_* tools can reuse the exact same spec without duplicating code.
# ---------------------------------------------------------------------------


def _prepare_equity_order(
    symbol: str,
    quantity: int,
    instruction: str,
    order_type: str,
    price: float | None = None,
    stop_price: float | None = None,
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
) -> dict[str, Any]:
    builder = _build_equity_order_spec(
        symbol, quantity, instruction, order_type, price, stop_price
    )
    builder = _apply_order_settings(builder, session, duration)
    return cast(dict[str, Any], builder.build())


def _prepare_option_order(
    symbol: str,
    quantity: int,
    instruction: str,
    order_type: str,
    price: float | None = None,
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
) -> dict[str, Any]:
    builder = _build_option_order_spec(symbol, quantity, instruction, order_type, price)
    builder = _apply_order_settings(builder, session, duration)
    return cast(dict[str, Any], builder.build())


def _prepare_trailing_stop_order(
    symbol: str,
    quantity: int,
    instruction: str,
    trail_offset: float,
    trail_type: str | None = "VALUE",
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
) -> dict[str, Any]:
    builder = _build_trailing_stop_order_spec(
        symbol, quantity, instruction, trail_offset, trail_type or "VALUE"
    )
    builder = _apply_order_settings(builder, session, duration)
    return cast(dict[str, Any], builder.build())


def _prepare_oco_order(
    first_order: "OrderDesc",
    second_order: "OrderDesc",
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
) -> dict[str, Any]:
    try:
        first_builder = _build_order_from_desc(first_order, session, duration)
    except ValueError as exc:
        raise ValueError(f"first_order: {exc}") from exc
    try:
        second_builder = _build_order_from_desc(second_order, session, duration)
    except ValueError as exc:
        raise ValueError(f"second_order: {exc}") from exc
    oco_order_builder = oco_builder(first_builder, second_builder)
    return cast(dict[str, Any], oco_order_builder.build())


def _prepare_trigger_order(
    entry_order: "OrderDesc",
    exit_orders: "list[OrderDesc]",
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
) -> dict[str, Any]:
    if len(exit_orders) not in (1, 2):
        raise ValueError("exit_orders must contain 1 or 2 orders")
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
        trig_builder = trigger_builder(entry_builder, exit_builders[0])
    else:
        oco_exit = oco_builder(exit_builders[0], exit_builders[1])
        trig_builder = trigger_builder(entry_builder, oco_exit)
    return cast(dict[str, Any], trig_builder.build())


def _prepare_bracket_order(
    symbol: str,
    quantity: int,
    entry_instruction: str,
    entry_type: str,
    profit_price: float | None = None,
    loss_price: float | None = None,
    entry_price: float | None = None,
    entry_stop_price: float | None = None,
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
    exit_session: str | None = None,
    exit_duration: str | None = None,
    loss_type: str = "STOP",
    loss_limit_price: float | None = None,
) -> dict[str, Any]:
    if profit_price is None and loss_price is None:
        raise ValueError("At least one of profit_price or loss_price must be provided")
    entry_instruction = entry_instruction.upper()
    if entry_instruction not in ["BUY", "SELL"]:
        raise ValueError(
            f"Invalid entry_instruction: {entry_instruction}. Use BUY or SELL."
        )
    exit_instruction = "SELL" if entry_instruction == "BUY" else "BUY"
    eff_exit_session = exit_session if exit_session is not None else session
    eff_exit_duration = exit_duration if exit_duration is not None else duration
    entry_order_builder = _build_equity_order_spec(
        symbol,
        quantity,
        entry_instruction,
        entry_type,
        price=entry_price,
        stop_price=entry_stop_price,
    )
    entry_order_builder = _apply_order_settings(entry_order_builder, session, duration)
    bracket_builder = _build_bracket_exit_order(
        entry_order_builder,
        symbol,
        quantity,
        exit_instruction,
        profit_price,
        loss_price,
        eff_exit_session,
        eff_exit_duration,
        loss_type=loss_type,
        loss_limit_price=loss_limit_price,
    )
    return cast(dict[str, Any], bracket_builder.build())


def _prepare_option_combo_order(
    legs: list[dict[str, Any]],
    order_type: str,
    price: float | None = None,
    session: str | None = "NORMAL",
    duration: str | None = "DAY",
    complex_order_strategy_type: str | None = "CUSTOM",
) -> dict[str, Any]:
    if not legs or len(legs) < 2:
        raise ValueError("Provide at least two option legs for a combo order")
    builder = OrderBuilder(enforce_enums=False).set_order_strategy_type("SINGLE")
    builder = _apply_order_settings(builder, session, duration)
    if complex_order_strategy_type:
        builder = builder.set_complex_order_strategy_type(
            complex_order_strategy_type.upper()
        )
    builder = builder.set_order_type(order_type.upper())
    if price is not None:
        builder = builder.set_price(price)
    for leg in legs:
        builder = builder.add_option_leg(
            leg["instruction"], leg["symbol"], leg["quantity"]
        )
    return cast(dict[str, Any], builder.build())


# ---------------------------------------------------------------------------
# _order_summary — builds a short human-readable summary for Discord reviewers.
# ---------------------------------------------------------------------------


def _order_summary_equity(
    instruction: str,
    quantity: int,
    symbol: str,
    order_type: str,
    price: float | None = None,
    stop_price: float | None = None,
) -> str:
    parts = [instruction.upper(), str(quantity), symbol, order_type.upper()]
    if price is not None:
        parts.append(f"@ ${price:.2f}")
    if stop_price is not None:
        parts.append(f"stop ${stop_price:.2f}")
    return " ".join(parts)


def _preview_action(account_hash: str, preview_id: str) -> str:
    return (
        f"Call place_previewed_order(account_hash='{account_hash}', "
        f"preview_id='{preview_id}') to execute this exact order."
    )


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
    Cancels a pending order. Cannot cancel executed/terminal orders. Params: account_hash, order_id. Returns updated order details (compact/pruned, same shape as get_order) after cancellation; falls back to a minimal {orderId, status, note} payload if the post-cancel status fetch fails or returns no data. *Write operation.*
    """
    client = ctx.orders
    await call(client.cancel_order, order_id=order_id, account_hash=account_hash)
    fallback: JSONType = {
        "orderId": order_id,
        "status": "PENDING_CANCEL",
        "note": "Cancel submitted; status fetch failed",
    }
    try:
        result = await call(
            client.get_order, order_id=order_id, account_hash=account_hash
        )
    except SchwabAPIError:
        return fallback
    if not isinstance(result, dict):
        return fallback
    return _prune_order(result)


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


def _build_bracket_exit_order(
    entry_order_builder: Any,
    symbol: str,
    quantity: int,
    exit_instruction: str,
    profit_price: float | None,
    loss_price: float | None,
    exit_session: str | None,
    exit_duration: str | None,
    loss_type: str = "STOP",
    loss_limit_price: float | None = None,
) -> Any:
    """Build the exit leg(s) for a bracket order and assemble the
    TRIGGER > OCO/SINGLE builder around the given entry leg."""
    if profit_price is None and loss_price is None:
        raise ValueError("At least one of profit_price or loss_price must be provided")

    profit_order_builder = None
    if profit_price is not None:
        profit_order_builder = _build_equity_order_spec(
            symbol, quantity, exit_instruction, "LIMIT", price=profit_price
        )
        profit_order_builder = _apply_order_settings(
            profit_order_builder, exit_session, exit_duration
        )

    loss_order_builder = None
    if loss_price is None:
        if loss_type.upper() != "STOP" or loss_limit_price is not None:
            raise ValueError(
                "loss_type/loss_limit_price require loss_price to be provided"
            )
    else:
        loss_type = loss_type.upper()
        if loss_type not in _BRACKET_LOSS_TYPES:
            raise ValueError(
                f"Invalid loss_type: {loss_type}. Must be one of: STOP, STOP_LIMIT, LIMIT"
            )
        if loss_type == "STOP_LIMIT" and loss_limit_price is None:
            raise ValueError("STOP_LIMIT loss orders require loss_limit_price")
        if loss_type != "STOP_LIMIT" and loss_limit_price is not None:
            raise ValueError(
                f"{loss_type} loss orders should not include loss_limit_price"
            )
        if loss_type == "STOP":
            ot, p, sp = "STOP", None, loss_price
        elif loss_type == "LIMIT":
            ot, p, sp = "LIMIT", loss_price, None
        else:  # STOP_LIMIT
            ot, p, sp = "STOP_LIMIT", loss_limit_price, loss_price
        loss_order_builder = _build_equity_order_spec(
            symbol, quantity, exit_instruction, ot, price=p, stop_price=sp
        )
        loss_order_builder = _apply_order_settings(
            loss_order_builder, exit_session, exit_duration
        )

    if profit_order_builder is not None and loss_order_builder is not None:
        # Both prices: entry triggers OCO(profit, loss)
        oco_exit_order_builder = oco_builder(profit_order_builder, loss_order_builder)
        return trigger_builder(entry_order_builder, oco_exit_order_builder)
    if loss_order_builder is not None:
        # Stop-loss only: entry triggers single stop order
        return trigger_builder(entry_order_builder, loss_order_builder)
    # Take-profit only: entry triggers single limit order
    return trigger_builder(entry_order_builder, profit_order_builder)


# ---------------------------------------------------------------------------
# preview_* tools — call Schwab's previewOrder, cache spec, return preview+id.
# All are read-only (no live market consequence, no Discord approval needed).
# ---------------------------------------------------------------------------


async def preview_equity_order(
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
    Preview an equity order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_equity_order(
        symbol, quantity, instruction, order_type, price, stop_price, session, duration
    )
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    summary = _order_summary_equity(
        instruction, quantity, symbol, order_type, price, stop_price
    )
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_equity_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def preview_option_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[
        str,
        "Option symbol in Schwab's space-delimited format (e.g., 'SPY 230616C400'). Use create_option_symbol() to build one.",
    ],
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
    Preview an option order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_option_order(
        symbol, quantity, instruction, order_type, price, session, duration
    )
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    summary = _order_summary_equity(instruction, quantity, symbol, order_type, price)
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_option_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def preview_equity_trailing_stop_order(
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
    Preview a trailing stop order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_trailing_stop_order(
        symbol, quantity, instruction, trail_offset, trail_type, session, duration
    )
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    eff_trail_type = (trail_type or "VALUE").upper()
    summary = f"{instruction.upper()} {quantity} {symbol} TRAILING_STOP offset={trail_offset} {eff_trail_type}"
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_equity_trailing_stop_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def preview_oco_order(
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
    Preview an OCO order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_oco_order(first_order, second_order, session, duration)
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    summary = (
        f"OCO: {first_order['instruction']} {first_order['quantity']} "
        f"{first_order['symbol']} + 1 other"
    )
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_oco_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def preview_trigger_order(
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
    Preview a trigger order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_trigger_order(
        entry_order, exit_orders, session, duration
    )
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    summary = (
        f"TRIGGER: {entry_order['instruction']} {entry_order['quantity']} "
        f"{entry_order['symbol']} + {len(exit_orders)} exit(s)"
    )
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_trigger_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def preview_bracket_order(
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
        float | None,
        "Stop-loss exit price (optional if profit_price provided). Trigger price "
        "for STOP/STOP_LIMIT loss_type (default); fill price for LIMIT loss_type. "
        "Required whenever loss_type or loss_limit_price is set.",
    ] = None,
    loss_type: Annotated[
        str,
        "Order type for the stop-loss exit leg: STOP (default), STOP_LIMIT, or LIMIT. "
        "Requires loss_price to be set.",
    ] = "STOP",
    loss_limit_price: Annotated[
        float | None,
        "Limit fill price for the loss leg; required when loss_type is STOP_LIMIT "
        "(and rejected otherwise). loss_price remains the stop trigger price in that case.",
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
    Preview a bracket order without placing it. Returns Schwab's projected
    order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.

    loss_price defaults to building a STOP exit order (trigger price) unless
    loss_type overrides it to STOP_LIMIT or LIMIT, in which case loss_price is
    the trigger/fill price respectively; loss_type and loss_limit_price require
    loss_price to be set. profit_price always builds a LIMIT exit order.
    """
    bracket_order_dict = _prepare_bracket_order(
        symbol,
        quantity,
        entry_instruction,
        entry_type,
        profit_price,
        loss_price,
        entry_price,
        entry_stop_price,
        session,
        duration,
        exit_session,
        exit_duration,
        loss_type=loss_type,
        loss_limit_price=loss_limit_price,
    )
    preview = await call(
        ctx.orders.preview_order,
        account_hash=account_hash,
        order_spec=bracket_order_dict,
    )
    summary = (
        f"BRACKET: {entry_instruction.upper()} {quantity} {symbol} {entry_type.upper()}"
        + (f" @ ${entry_price:.2f}" if entry_price else "")
        + " + exits"
        + (
            f" (loss: {loss_type.upper()})"
            if loss_price is not None and loss_type.upper() != "STOP"
            else ""
        )
    )
    resolved_leg_types: dict[str, str] = {"entry": entry_type.upper()}
    if profit_price is not None:
        resolved_leg_types["profit"] = "LIMIT"
    if loss_price is not None:
        resolved_leg_types["loss"] = loss_type.upper()
    preview_id = ctx.previews.put(
        account_hash, bracket_order_dict, "preview_bracket_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
        "resolved_leg_types": resolved_leg_types,
    }


async def preview_option_combo_order(
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
    Preview a multi-leg option combo order without placing it. Returns Schwab's
    projected order details (validation results, commission/fees) plus a preview_id.
    Call place_previewed_order(account_hash, preview_id) to execute this
    exact order. Params: same as this order shape's fields below.
    """
    order_spec_dict = _prepare_option_combo_order(
        legs, order_type, price, session, duration, complex_order_strategy_type
    )
    preview = await call(
        ctx.orders.preview_order, account_hash=account_hash, order_spec=order_spec_dict
    )
    summary = f"COMBO: {len(legs)} option legs, {order_type.upper()}"
    preview_id = ctx.previews.put(
        account_hash, order_spec_dict, "preview_option_combo_order", summary
    )
    return {
        "preview_id": preview_id,
        "preview": preview,
        "action": _preview_action(account_hash, preview_id),
    }


async def place_previewed_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    preview_id: Annotated[str, "Preview ID returned by a preview_* tool"],
) -> JSONType:
    """
    Places a previously previewed order using its exact cached order
    specification (no re-derivation from parameters). Call a preview_*
    tool first to get a preview_id, review the projected order details,
    then call this tool to execute. Previews expire after 10 minutes and
    are single-use. Returns updated order details (compact/pruned, same
    shape as get_order) after placement; falls back to a minimal
    {orderId, accountHash, note} payload if the post-placement status fetch
    fails or returns no data. *Write operation.*
    """
    entry = ctx.previews.pop(preview_id, account_hash)

    request = ApprovalRequest(
        id=str(uuid.uuid4()),
        tool_name="place_previewed_order",
        request_id=ctx.request_id,
        client_id=ctx.client_id,
        arguments={
            "original_tool": entry.tool_name,
            "order_summary": entry.summary,
            "preview_id": preview_id,
            "account_hash": account_hash,
        },
    )

    decision = await run_approval(ctx, request)
    if decision is ApprovalDecision.APPROVED:
        placed = await call(
            ctx.orders.place_order,
            account_hash=account_hash,
            order_spec=entry.order_spec,
            response_handler=_order_response_handler(ctx, account_hash),
        )
        order_id = placed.get("orderId") if isinstance(placed, dict) else None
        if order_id is None:
            return placed
        order_id = str(order_id)
        fallback: JSONType = {
            "orderId": order_id,
            "accountHash": account_hash,
            "note": "Order placed; status fetch failed",
        }
        try:
            result = await call(
                ctx.orders.get_order, order_id=order_id, account_hash=account_hash
            )
        except (SchwabAPIError, ValueError):
            return fallback
        if not isinstance(result, dict):
            return fallback
        return _prune_order(result)

    message = (
        "Order placement denied by reviewer."
        if decision is ApprovalDecision.DENIED
        else "Approval request for order placement expired."
    )
    await ctx.warning(message)
    if decision is ApprovalDecision.DENIED:
        raise PermissionError(message)
    raise TimeoutError(message)


_READ_ONLY_TOOLS = (
    get_order,
    get_orders,
    create_option_symbol,
    preview_equity_order,
    preview_option_order,
    preview_equity_trailing_stop_order,
    preview_oco_order,
    preview_trigger_order,
    preview_bracket_order,
    preview_option_combo_order,
)

_WRITE_TOOLS = (cancel_order,)  # keeps automatic argument-dump approval


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

    # place_previewed_order builds its own ApprovalRequest (with the
    # cached human-readable summary) instead of a raw argument dump, so
    # it must bypass register_tool's automatic write=True wrapping.
    register_tool(
        server,
        place_previewed_order,
        write=False,
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        result_transform=result_transform,
    )
