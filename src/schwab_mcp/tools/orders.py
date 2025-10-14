#

from typing import Annotated, Any, cast

import datetime
from schwab.orders.common import one_cancels_other as oco_builder
from schwab.orders.common import first_triggers_second as trigger_builder

from schwab_mcp.tools.order_helpers import (
    equity_buy_market,
    equity_sell_market,
    equity_buy_limit,
    equity_sell_limit,
    equity_buy_stop,
    equity_sell_stop,
    equity_buy_stop_limit,
    equity_sell_stop_limit,
    option_buy_to_open_market,
    option_sell_to_open_market,
    option_buy_to_close_market,
    option_sell_to_close_market,
    option_buy_to_open_limit,
    option_sell_to_open_limit,
    option_buy_to_close_limit,
    option_sell_to_close_limit,
)
from schwab.orders.options import OptionSymbol
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import JSONType, call


# Internal helper function to apply session and duration settings
def _apply_order_settings(order_spec, session: str | None, duration: str | None):
    """Internal helper to apply session and duration to an order spec builder."""
    if session:
        order_spec = order_spec.set_session(session)
    # Apply duration only if it's provided and applicable (not None)
    # Let schwab-py or the API handle invalid duration types for specific orders
    if duration:
        order_spec = order_spec.set_duration(duration)
    return order_spec


# Internal helper function to build the core equity order spec builder
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

    # Validate parameters and create the appropriate order spec builder
    if order_type == "MARKET":
        if price is not None or stop_price is not None:
            raise ValueError("MARKET orders should not include price or stop_price")
        if instruction == "BUY":
            return equity_buy_market(symbol, quantity)
        elif instruction == "SELL":
            return equity_sell_market(symbol, quantity)
        else:
            raise ValueError(
                f"Invalid instruction for MARKET order: {instruction}. Use BUY or SELL."
            )

    elif order_type == "LIMIT":
        if price is None:
            raise ValueError("LIMIT orders require a price")
        if stop_price is not None:
            raise ValueError("LIMIT orders should not include stop_price")
        if instruction == "BUY":
            return equity_buy_limit(symbol, quantity, price)
        elif instruction == "SELL":
            return equity_sell_limit(symbol, quantity, price)
        else:
            raise ValueError(
                f"Invalid instruction for LIMIT order: {instruction}. Use BUY or SELL."
            )

    elif order_type == "STOP":
        if stop_price is None:
            raise ValueError("STOP orders require a stop_price")
        if price is not None:
            raise ValueError("STOP orders should not include price")
        if instruction == "BUY":
            return equity_buy_stop(symbol, quantity, stop_price)
        elif instruction == "SELL":
            return equity_sell_stop(symbol, quantity, stop_price)
        else:
            raise ValueError(
                f"Invalid instruction for STOP order: {instruction}. Use BUY or SELL."
            )

    elif order_type == "STOP_LIMIT":
        if stop_price is None or price is None:
            raise ValueError("STOP_LIMIT orders require both stop_price and price")
        if instruction == "BUY":
            return equity_buy_stop_limit(symbol, quantity, stop_price, price)
        elif instruction == "SELL":
            return equity_sell_stop_limit(symbol, quantity, stop_price, price)
        else:
            raise ValueError(
                f"Invalid instruction for STOP_LIMIT order: {instruction}. Use BUY or SELL."
            )

    else:
        raise ValueError(
            f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT, STOP, STOP_LIMIT"
        )


# Internal helper function to build the core option order spec builder
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

    # Validate parameters and create the appropriate order spec builder
    if order_type == "MARKET":
        if price is not None:
            raise ValueError("MARKET orders should not include a price parameter")
        if instruction == "BUY_TO_OPEN":
            return option_buy_to_open_market(symbol, quantity)
        elif instruction == "SELL_TO_OPEN":
            return option_sell_to_open_market(symbol, quantity)
        elif instruction == "BUY_TO_CLOSE":
            return option_buy_to_close_market(symbol, quantity)
        elif instruction == "SELL_TO_CLOSE":
            return option_sell_to_close_market(symbol, quantity)
        else:
            raise ValueError(
                f"Invalid instruction for MARKET option order: {instruction}. Use BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, or SELL_TO_CLOSE."
            )

    elif order_type == "LIMIT":
        if price is None:
            raise ValueError("LIMIT orders require a price parameter")
        if instruction == "BUY_TO_OPEN":
            return option_buy_to_open_limit(symbol, quantity, price)
        elif instruction == "SELL_TO_OPEN":
            return option_sell_to_open_limit(symbol, quantity, price)
        elif instruction == "BUY_TO_CLOSE":
            return option_buy_to_close_limit(symbol, quantity, price)
        elif instruction == "SELL_TO_CLOSE":
            return option_sell_to_close_limit(symbol, quantity, price)
        else:
            raise ValueError(
                f"Invalid instruction for LIMIT option order: {instruction}. Use BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, or SELL_TO_CLOSE."
            )

    else:
        raise ValueError(
            f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT"
        )


@register
async def get_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to get details for"],
) -> JSONType:
    """
    Returns details for a specific order (ID, status, price, quantity, execution details). Params: account_hash, order_id.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders
    return await call(client.get_order, order_id=order_id, account_hash=account_hash)


@register
async def get_orders(
    ctx: SchwabContext,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_account_numbers)"
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
) -> JSONType:
    """
    Returns order history for an account. Filter by date range (max 60 days past) and status.
    Params: account_hash, max_results, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD), status (list/str).
    Status options: AWAITING_PARENT_ORDER, AWAITING_CONDITION, AWAITING_STOP_CONDITION, AWAITING_MANUAL_REVIEW, ACCEPTED, AWAITING_UR_OUT, PENDING_ACTIVATION, QUEUED, WORKING, REJECTED, PENDING_CANCEL, CANCELED, PENDING_REPLACE, REPLACED, FILLED, EXPIRED, NEW, AWAITING_RELEASE_TIME, PENDING_ACKNOWLEDGEMENT, PENDING_RECALL.
    Use tomorrow's date as to_date for today's orders. Use WORKING/PENDING_ACTIVATION for open orders.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    from_date_obj = None
    to_date_obj = None

    if from_date is not None:
        from_date_obj = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date_obj = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    # Map status to enums; support list via 'statuses'
    kwargs: dict[str, Any] = {
        "max_results": max_results,
        "from_entered_datetime": from_date_obj,
        "to_entered_datetime": to_date_obj,
    }

    if status:
        if isinstance(status, str):
            kwargs["status"] = client.Order.Status[status.upper()]
        else:
            kwargs["statuses"] = [client.Order.Status[s.upper()] for s in status]

    return await call(
        client.get_orders_for_account,
        account_hash,
        **kwargs,
    )


@register(write=True)
async def cancel_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to cancel"],
) -> JSONType:
    """
    Cancels a pending order. Cannot cancel executed/terminal orders. Params: account_hash, order_id. Returns cancellation request confirmation; check status after. *Write operation.*
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders
    return await call(client.cancel_order, order_id=order_id, account_hash=account_hash)


@register(write=True)
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
        "Order duration: DAY (default), GOOD_TILL_CANCEL, FILL_OR_KILL (Limit/StopLimit only)",
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
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    order_spec_builder = _build_equity_order_spec(
        symbol, quantity, instruction, order_type, price, stop_price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build the final order dictionary
    order_spec_dict = cast(dict[str, Any], order_spec_builder.build())

    # Place the order
    return await call(
        client.place_order, account_hash=account_hash, order_spec=order_spec_dict
    )


@register(write=True)
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
        "Order duration: DAY (default), GOOD_TILL_CANCEL, FILL_OR_KILL (Limit only)",
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
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    order_spec_builder = _build_option_order_spec(
        symbol, quantity, instruction, order_type, price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build the final order dictionary
    order_spec_dict = cast(dict[str, Any], order_spec_builder.build())

    # Place the order
    return await call(
        client.place_order, account_hash=account_hash, order_spec=order_spec_dict
    )


@register
async def build_equity_order_spec(
    symbol: Annotated[str, "Stock symbol"],
    quantity: Annotated[int, "Number of shares"],
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
        "Order duration: DAY (default), GOOD_TILL_CANCEL, FILL_OR_KILL (Limit/StopLimit only)",
    ] = "DAY",
) -> dict[str, Any]:
    """
    Builds an equity order specification dictionary suitable for complex orders (OCO, Trigger).
    Params: symbol, quantity, instruction (BUY/SELL), order_type (MARKET/LIMIT/STOP/STOP_LIMIT).
    Optional/Conditional: price (for LIMIT/STOP_LIMIT), stop_price (for STOP/STOP_LIMIT), session (default NORMAL), duration (default DAY).
    Returns the order specification dictionary, does NOT place the order.
    """
    # Build the core order specification builder
    order_spec_builder = _build_equity_order_spec(
        symbol, quantity, instruction, order_type, price, stop_price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build and return the specification dictionary
    return cast(dict[str, Any], order_spec_builder.build())


@register
async def build_option_order_spec(
    symbol: Annotated[str, "Option symbol (e.g., 'SPY_230616C400')"],
    quantity: Annotated[int, "Number of contracts"],
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
        "Order duration: DAY (default), GOOD_TILL_CANCEL, FILL_OR_KILL (Limit only)",
    ] = "DAY",
) -> dict[str, Any]:
    """
    Builds an option order specification dictionary suitable for complex orders (OCO, Trigger).
    Params: symbol, quantity, instruction (BUY_TO_OPEN/etc.), order_type (MARKET/LIMIT).
    Optional/Conditional: price (for LIMIT), session (default NORMAL), duration (default DAY).
    Returns the order specification dictionary, does NOT place the order.
    """
    # Build the core order specification builder
    order_spec_builder = _build_option_order_spec(
        symbol, quantity, instruction, order_type, price
    )

    # Apply session and duration settings using the internal helper
    order_spec_builder = _apply_order_settings(order_spec_builder, session, duration)

    # Build and return the specification dictionary
    return cast(dict[str, Any], order_spec_builder.build())


@register(write=True)
async def place_one_cancels_other_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    first_order_spec: Annotated[
        dict, "First order specification (dict from build_equity/option_order_spec)"
    ],
    second_order_spec: Annotated[
        dict, "Second order specification (dict from build_equity/option_order_spec)"
    ],
) -> JSONType:
    """
    Creates OCO order: execution of one cancels the other. Use for take-profit/stop-loss pairs.
    Params: account_hash, first_order_spec (dict), second_order_spec (dict).
    *Use build_equity_order_spec() or build_option_order_spec() to create the required spec dictionaries.* *Write operation.*
    """
    # Manually construct the OCO order dictionary structure
    # This structure is correct according to schwab-py's oco_builder
    oco_order_spec = {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [first_order_spec, second_order_spec],
    }

    # Place the order
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    return await call(
        client.place_order, account_hash=account_hash, order_spec=oco_order_spec
    )


@register(write=True)
async def place_first_triggers_second_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    first_order_spec: Annotated[
        dict,
        "First (primary) order specification (dict from build_equity/option_order_spec)",
    ],
    second_order_spec: Annotated[
        dict,
        "Second (triggered) order specification (dict from build_equity/option_order_spec)",
    ],
) -> JSONType:
    """
    Creates conditional order: second order placed only after first executes. Use for activating exits after entry.
    Params: account_hash, first_order_spec (dict), second_order_spec (dict).
    *Use build_equity_order_spec() or build_option_order_spec() to create the required spec dictionaries.* *Write operation.*
    """
    # Manually construct the Trigger order dictionary structure
    # According to schwab-py's trigger_builder, the second order becomes a child of the first.
    # We modify the first spec dictionary directly.
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    trigger_order_spec = (
        first_order_spec.copy()
    )  # Avoid modifying the original input dict
    trigger_order_spec["orderStrategyType"] = "TRIGGER"
    trigger_order_spec["childOrderStrategies"] = [second_order_spec]

    # Place the order
    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=trigger_order_spec,
    )


@register(write=True)
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


@register(write=True)
async def place_bracket_order(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    symbol: Annotated[str, "Stock symbol to trade"],
    quantity: Annotated[int, "Number of shares to trade"],
    entry_instruction: Annotated[str, "BUY or SELL for the entry order"],
    entry_type: Annotated[str, "Entry order type: MARKET, LIMIT, STOP, or STOP_LIMIT"],
    profit_price: Annotated[float, "Take-profit limit price"],
    loss_price: Annotated[float, "Stop-loss trigger price"],
    entry_price: Annotated[
        float | None, "Required for LIMIT entry; Limit price for STOP_LIMIT entry"
    ] = None,
    entry_stop_price: Annotated[
        float | None, "Required for STOP and STOP_LIMIT entry orders"
    ] = None,
    session: Annotated[
        str | None, "Trading session: NORMAL (default), AM, PM, or SEAMLESS"
    ] = "NORMAL",
    duration: Annotated[
        str | None, "Order duration: DAY (default), GOOD_TILL_CANCEL"
    ] = "DAY",
) -> JSONType:
    """
    Creates a bracket order: entry + OCO take-profit/stop-loss. Exits trigger after entry executes.
    Params: account_hash, symbol, quantity, entry_instruction (BUY/SELL), entry_type (MARKET/LIMIT/STOP/STOP_LIMIT), profit_price, loss_price.
    Optional/Conditional: entry_price (for LIMIT/STOP_LIMIT), entry_stop_price (for STOP/STOP_LIMIT), session (default NORMAL), duration (default DAY).
    Ensure profit/loss prices are correctly positioned relative to entry (e.g., profit > entry for BUY).
    Note: Duration applies to all legs of the order. FILL_OR_KILL is not typically used with bracket orders.
    *Write operation.*
    """
    # Validate entry instruction
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.orders

    entry_instruction = entry_instruction.upper()
    if entry_instruction not in ["BUY", "SELL"]:
        raise ValueError(
            f"Invalid entry_instruction: {entry_instruction}. Use BUY or SELL."
        )

    # Determine exit instructions (opposite of entry)
    exit_instruction = "SELL" if entry_instruction == "BUY" else "BUY"

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

    # Create take-profit (limit) order spec builder
    if exit_instruction == "BUY":
        profit_order_builder = equity_buy_limit(symbol, quantity, profit_price)
    else:  # SELL
        profit_order_builder = equity_sell_limit(symbol, quantity, profit_price)
    # Apply settings to profit order builder
    profit_order_builder = _apply_order_settings(
        profit_order_builder, session, duration
    )

    # Create stop-loss (stop) order spec builder
    if exit_instruction == "BUY":
        loss_order_builder = equity_buy_stop(symbol, quantity, loss_price)
    else:  # SELL
        loss_order_builder = equity_sell_stop(symbol, quantity, loss_price)
    # Apply settings to loss order builder
    loss_order_builder = _apply_order_settings(loss_order_builder, session, duration)

    # Create OCO order builder for take-profit and stop-loss using the builder helper
    oco_exit_order_builder = oco_builder(profit_order_builder, loss_order_builder)

    # Create the trigger order builder (entry triggers OCO) using the builder helper
    bracket_order_builder = trigger_builder(entry_order_builder, oco_exit_order_builder)

    # Build the final complex bracket order dictionary
    bracket_order_dict = cast(dict[str, Any], bracket_order_builder.build())

    # Place the complex bracket order
    return await call(
        client.place_order,
        account_hash=account_hash,
        order_spec=bracket_order_dict,
    )
