#

from schwab.orders.common import (
    OrderType,
    Session,
    Duration,
    OrderStrategyType,
    EquityInstruction,
    OptionInstruction,
)
from schwab.orders.generic import OrderBuilder


def __equity_base_builder(session=Session.NORMAL, duration=Duration.DAY):
    """
    Returns a base OrderBuilder for equity orders with common settings.
    """
    return (
        OrderBuilder(enforce_enums=False)
        .set_session(session)
        .set_duration(duration)
        .set_order_strategy_type(OrderStrategyType.SINGLE)
    )


def equity_buy_market(symbol, quantity, duration=Duration.DAY, session=Session.NORMAL):
    """
    Returns a pre-filled OrderBuilder for an equity buy market order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_equity_leg(EquityInstruction.BUY, symbol, quantity)
    )


def equity_sell_market(symbol, quantity, duration=Duration.DAY, session=Session.NORMAL):
    """
    Returns a pre-filled OrderBuilder for an equity sell market order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_equity_leg(EquityInstruction.SELL, symbol, quantity)
    )


def equity_buy_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for an equity buy limit order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_equity_leg(EquityInstruction.BUY, symbol, quantity)
    )


def equity_sell_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for an equity sell limit order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_equity_leg(EquityInstruction.SELL, symbol, quantity)
    )


def equity_buy_stop(
    symbol, quantity, stop_price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for an equity buy stop order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.STOP)
        .set_stop_price(str(stop_price))
        .add_equity_leg(EquityInstruction.BUY, symbol, quantity)
    )


def equity_sell_stop(
    symbol, quantity, stop_price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for an equity sell stop order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.STOP)
        .set_stop_price(str(stop_price))
        .add_equity_leg(EquityInstruction.SELL, symbol, quantity)
    )


def equity_buy_stop_limit(
    symbol,
    quantity,
    stop_price,
    limit_price,
    duration=Duration.DAY,
    session=Session.NORMAL,
):
    """
    Returns a pre-filled OrderBuilder for an equity buy stop-limit order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.STOP_LIMIT)
        .set_stop_price(str(stop_price))
        .set_price(str(limit_price))
        .add_equity_leg(EquityInstruction.BUY, symbol, quantity)
    )


def equity_sell_stop_limit(
    symbol,
    quantity,
    stop_price,
    limit_price,
    duration=Duration.DAY,
    session=Session.NORMAL,
):
    """
    Returns a pre-filled OrderBuilder for an equity sell stop-limit order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.STOP_LIMIT)
        .set_stop_price(str(stop_price))
        .set_price(str(limit_price))
        .add_equity_leg(EquityInstruction.SELL, symbol, quantity)
    )


def __option_base_builder(session=Session.NORMAL, duration=Duration.DAY):
    """
    Returns a base OrderBuilder for option orders with common settings.
    """
    return (
        OrderBuilder(enforce_enums=False)
        .set_session(session)
        .set_duration(duration)
        .set_order_strategy_type(OrderStrategyType.SINGLE)
    )


def option_buy_to_open_market(
    symbol, quantity, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a buy-to-open market order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_option_leg(OptionInstruction.BUY_TO_OPEN, symbol, quantity)
    )


def option_sell_to_open_market(
    symbol, quantity, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a sell-to-open market order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_option_leg(OptionInstruction.SELL_TO_OPEN, symbol, quantity)
    )


def option_buy_to_close_market(
    symbol, quantity, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a buy-to-close market order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_option_leg(OptionInstruction.BUY_TO_CLOSE, symbol, quantity)
    )


def option_sell_to_close_market(
    symbol, quantity, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a sell-to-close market order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.MARKET)
        .add_option_leg(OptionInstruction.SELL_TO_CLOSE, symbol, quantity)
    )


def option_buy_to_open_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a buy-to-open limit order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_option_leg(OptionInstruction.BUY_TO_OPEN, symbol, quantity)
    )


def option_sell_to_open_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a sell-to-open limit order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_option_leg(OptionInstruction.SELL_TO_OPEN, symbol, quantity)
    )


def option_buy_to_close_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a buy-to-close limit order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_option_leg(OptionInstruction.BUY_TO_CLOSE, symbol, quantity)
    )


def option_sell_to_close_limit(
    symbol, quantity, price, duration=Duration.DAY, session=Session.NORMAL
):
    """
    Returns a pre-filled OrderBuilder for a sell-to-close limit order.
    """
    return (
        __option_base_builder(session, duration)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
        .add_option_leg(OptionInstruction.SELL_TO_CLOSE, symbol, quantity)
    )


def equity_trailing_stop(
    symbol,
    quantity,
    instruction,
    stop_price_offset,
    stop_price_link_type="VALUE",
    duration=Duration.DAY,
    session=Session.NORMAL,
):
    """
    Returns a pre-filled OrderBuilder for an equity trailing stop order.
    """
    return (
        __equity_base_builder(session, duration)
        .set_order_type(OrderType.TRAILING_STOP)
        .set_stop_price_offset(stop_price_offset)
        .set_stop_price_link_type(stop_price_link_type)
        .set_stop_price_link_basis("LAST")
        .add_equity_leg(instruction, symbol, quantity)
    )
