#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_option_chain(
    client: schwab.client.AsyncClient,
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
        str | None, "Start date for option expiration ('YYYY-MM-DD')"
    ] = None,
    to_date: Annotated[
        str | None, "End date for option expiration ('YYYY-MM-DD')"
    ] = None,
) -> str:
    """
    Returns option chain data (strikes, expirations, prices) for a symbol. Use for standard chains.
    Params: symbol, contract_type (CALL/PUT/ALL), strike_count (default 25), include_quotes (bool), from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
    Limit data returned using strike_count and date parameters.
    """
    if from_date is not None:
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type]
        if contract_type
        else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        from_date=from_date,
        to_date=to_date,
    )


@register
async def get_advanced_option_chain(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the underlying security"],
    contract_type: Annotated[str | None, "Type of contracts: CALL, PUT, or ALL (default)"] = None,
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
        str | None, "Filter strikes: IN_THE_MONEY, NEAR_THE_MONEY, OUT_OF_THE_MONEY, STRIKES_ABOVE_MARKET, STRIKES_BELOW_MARKET, STRIKES_NEAR_MARKET, ALL (default)"
    ] = None,
    from_date: Annotated[str | None, "Start date for options ('YYYY-MM-DD')"] = None,
    to_date: Annotated[str | None, "End date for options ('YYYY-MM-DD')"] = None,
    volatility: Annotated[
        float | None, "Volatility for ANALYTICAL strategy"
    ] = None,
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
    option_type: Annotated[str | None, "Filter option type: STANDARD, NON_STANDARD, ALL (default)"] = None,
) -> str:
    """
    Returns advanced option chain data with strategies, filters, and theoretical calculations. Use for complex analysis.
    Params: symbol, contract_type, strike_count, include_quotes, strategy (SINGLE/ANALYTICAL/etc.), interval, strike, strike_range (ITM/NTM/etc.), from/to_date, volatility/underlying_price/interest_rate/days_to_expiration (for ANALYTICAL), exp_month, option_type (STANDARD/NON_STANDARD/ALL).
    Limit data returned using strike_count and date parameters.
    """
    if from_date is not None:
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type]
        if contract_type
        else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        strategy=client.Options.Strategy[strategy] if strategy else None,
        interval=interval,
        strike=strike,
        strike_range=client.Options.StrikeRange[strike_range] if strike_range else None,
        from_date=from_date,
        to_date=to_date,
        volatility=volatility,
        underlying_price=underlying_price,
        interest_rate=interest_rate,
        days_to_expiration=days_to_expiration,
        exp_month=exp_month,
        option_type=client.Options.Type[option_type] if option_type else None,
    )


@register
async def get_option_expiration_chain(
    client: schwab.client.Client,
    symbol: Annotated[str, "Symbol of the underlying security"],
) -> str:
    """
    Returns available option expiration dates for a symbol, without contract details. Lightweight call to find available cycles. Param: symbol.
    """
    return await call(client.get_option_expiration_chain, symbol)
