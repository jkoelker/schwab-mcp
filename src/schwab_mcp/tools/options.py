#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_option_chain(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the underlying security"],
    contract_type: Annotated[str | None, "Type of contracts to return"] = None,
    strike_count: Annotated[
        int,
        "The Number of strikes to return above or below the at-the-money price",
    ] = 25,
    include_quotes: Annotated[bool | None, "Include quotes for the options"] = None,
    from_date: Annotated[str | None, "Start date for options"] = None,
    to_date: Annotated[str | None, "End date for options"] = None,
) -> str:
    """
    Get option chain for a specific symbol. This function is a simplified version of the
    `get_advanced_option_chain` function and should be used when fetching option chains
    without the need for advanced parameters.

    Contract type can be one of the following, if not provided all contracts will be returned:
      CALL
      PUT
      ALL

    IMPORTANT: This function may return a large amount of data, you should always
    use the strike_count and from_date/to_date parameters to limit the amount of data
    returned.
    """
    if from_date is not None:
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type] if contract_type else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        from_date=from_date,
        to_date=to_date,
    )

@register
async def get_advanced_option_chain(
    client: schwab.client.AsyncClient,
    symbol: Annotated[str, "Symbol of the underlying security"],
    contract_type: Annotated[str | None, "Type of contracts to return"] = None,
    strike_count: Annotated[
        int,
        "The Number of strikes to return above or below the at-the-money price",
    ] = 25,
    include_quotes: Annotated[bool | None, "Include quotes for the options"] = None,
    strategy: Annotated[
        str | None,
        (
            "Option chain strategy. Default is SINGLE. ANALYTICAL allows the use of "
            "volatility, underlyingPrice, interestRate, and daysToExpiration params "
            "to calculate theoretical values."
        ),
    ] = None,
    interval: Annotated[
        str | None, "Strike interval for spread strategy chains"
    ] = None,
    strike: Annotated[float | None, "Only return options with the given strike"] = None,
    strike_range: Annotated[
        str | None, "Only return options within the given range"
    ] = None,
    from_date: Annotated[str | None, "Start date for options"] = None,
    to_date: Annotated[str | None, "End date for options"] = None,
    volatility: Annotated[
        float | None, "Volatility to use in ANALITICAL strategy"
    ] = None,
    underlying_price: Annotated[
        float | None, "Underlying price to use in ANALITICAL strategy"
    ] = None,
    interest_rate: Annotated[
        float | None, "Interest rate to use in ANALITICAL strategy"
    ] = None,
    days_to_expiration: Annotated[
        int | None, "Days to expiration to use in ANALITICAL strategy"
    ] = None,
    exp_month: Annotated[
        str | None, "Expiration month to use in ANALITICAL strategy"
    ] = None,
    option_type: Annotated[str | None, "Types of options to return"] = None,
) -> str:
    """
    IMPORTANT you should use this function only if you need to use advanced parameters.

    Get advanced option chain for a specific symbol.

    Contract type can be one of the following, if not provided all contracts will be returned:
      CALL
      PUT
      ALL

    Strategy can be one of the following:
      SINGLE
      ANALYTICAL
      COVERED
      VERTICAL
      CALENDAR
      STRANGLE
      STRADDLE
      BUTTERFLY
      CONDOR
      DIAGONAL
      COLLAR
      ROLL

    Strike range can be one of the following, if not provided all strikes will be returned:
      IN_THE_MONEY
      NEAR_THE_MONEY
      OUT_OF_THE_MONEY
      STRIKES_ABOVE_MARKET
      STRIKES_BELOW_MARKET
      STRIKES_NEAR_MARKET
      ALL

    Option type can be one of the following, if not provided all options will be returned:
      STANDARD
      NON_STANDARD
      ALL

    IMPORTANT: This function may return a large amount of data, you should always
    use the strike_count and from_date/to_date parameters to limit the amount of data
    returned.
    """
    if from_date is not None:
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    return await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type] if contract_type else None,
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
    Get Option Expiration (Series) information for an optionable symbol.
    Does not include individual options contracts for the underlying.
    """
    return await call(client.get_option_expiration_chain, symbol)
