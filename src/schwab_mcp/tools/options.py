#

from typing import Annotated

import datetime

from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


def _parse_date(value: str | datetime.date | None) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    return datetime.datetime.strptime(value, "%Y-%m-%d").date()


@register
async def get_option_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security (e.g., 'AAPL', 'SPY')"],
    contract_type: Annotated[
        str | None, "Type of option contracts: CALL, PUT, or ALL (default)"
    ] = None,
    strike_count: Annotated[
        int,
        "Number of strikes above/below the at-the-money price (default: 25)",
    ] = 25,
    include_quotes: Annotated[
        bool | None, "Include underlying and option market quotes"
    ] = None,
    from_date: Annotated[
        str | datetime.date | None,
        "Start date for option expiration ('YYYY-MM-DD' or datetime.date)",
    ] = None,
    to_date: Annotated[
        str | datetime.date | None,
        "End date for option expiration ('YYYY-MM-DD' or datetime.date)",
    ] = None,
) -> str:
    """
    Returns option chain data (strikes, expirations, prices) for a symbol. Use for standard chains.
    Params: symbol, contract_type (CALL/PUT/ALL), strike_count (default 25), include_quotes (bool), from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
    Limit data returned using strike_count and date parameters.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.options

    from_date_obj = _parse_date(from_date)
    to_date_obj = _parse_date(to_date)

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type.upper()]
        if contract_type
        else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        from_date=from_date_obj,
        to_date=to_date_obj,
    )


@register
async def get_advanced_option_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security"],
    contract_type: Annotated[
        str | None, "Type of contracts: CALL, PUT, or ALL (default)"
    ] = None,
    strike_count: Annotated[
        int,
        "Number of strikes above/below the at-the-money price (default: 25)",
    ] = 25,
    include_quotes: Annotated[bool | None, "Include quotes for the options"] = None,
    strategy: Annotated[
        str | None,
        (
            "Option strategy: SINGLE (default), ANALYTICAL, COVERED, VERTICAL, CALENDAR, STRANGLE, STRADDLE, "
            "BUTTERFLY, CONDOR, DIAGONAL, COLLAR, ROLL"
        ),
    ] = None,
    interval: Annotated[
        str | None, "Strike interval for spread strategy chains"
    ] = None,
    strike: Annotated[float | None, "Only return options with the given strike"] = None,
    strike_range: Annotated[
        str | None,
        "Filter strikes: IN_THE_MONEY, NEAR_THE_MONEY, OUT_OF_THE_MONEY, STRIKES_ABOVE_MARKET, STRIKES_BELOW_MARKET, STRIKES_NEAR_MARKET, ALL (default)",
    ] = None,
    from_date: Annotated[
        str | datetime.date | None,
        "Start date for options ('YYYY-MM-DD' or datetime.date)",
    ] = None,
    to_date: Annotated[
        str | datetime.date | None,
        "End date for options ('YYYY-MM-DD' or datetime.date)",
    ] = None,
    volatility: Annotated[float | None, "Volatility for ANALYTICAL strategy"] = None,
    underlying_price: Annotated[
        float | None, "Underlying price for ANALYTICAL strategy"
    ] = None,
    interest_rate: Annotated[
        float | None, "Interest rate for ANALYTICAL strategy"
    ] = None,
    days_to_expiration: Annotated[
        int | None, "Days to expiration for ANALYTICAL strategy"
    ] = None,
    exp_month: Annotated[
        str | None, "Expiration month (e.g., JAN) for ANALYTICAL strategy"
    ] = None,
    option_type: Annotated[
        str | None, "Filter option type: STANDARD, NON_STANDARD, ALL (default)"
    ] = None,
) -> str:
    """
    Returns advanced option chain data with strategies, filters, and theoretical calculations. Use for complex analysis.
    Params: symbol, contract_type, strike_count, include_quotes, strategy (SINGLE/ANALYTICAL/etc.), interval, strike, strike_range (ITM/NTM/etc.), from/to_date, volatility/underlying_price/interest_rate/days_to_expiration (for ANALYTICAL), exp_month, option_type (STANDARD/NON_STANDARD/ALL).
    Limit data returned using strike_count and date parameters.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.options

    from_date_obj = _parse_date(from_date)
    to_date_obj = _parse_date(to_date)

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type.upper()]
        if contract_type
        else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        strategy=client.Options.Strategy[strategy.upper()] if strategy else None,
        interval=interval,
        strike=strike,
        strike_range=client.Options.StrikeRange[strike_range.upper()]
        if strike_range
        else None,
        from_date=from_date_obj,
        to_date=to_date_obj,
        volatility=volatility,
        underlying_price=underlying_price,
        interest_rate=interest_rate,
        days_to_expiration=days_to_expiration,
        exp_month=client.Options.ExpirationMonth[exp_month.upper()]
        if exp_month
        else None,
        option_type=client.Options.Type[option_type.upper()] if option_type else None,
    )


@register
async def get_option_expiration_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security"],
) -> str:
    """
    Returns available option expiration dates for a symbol, without contract details. Lightweight call to find available cycles. Param: symbol.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.options
    return await call(client.get_option_expiration_chain, symbol)
