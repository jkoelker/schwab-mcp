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
        str | None, "Type of option contracts to return (CALL, PUT, ALL)"
    ] = None,
    strike_count: Annotated[
        int,
        "Number of strikes to return above and below the at-the-money price",
    ] = 25,
    include_quotes: Annotated[
        bool | None, "Include underlying and option market quotes"
    ] = None,
    from_date: Annotated[
        str | None, "Start date for option expiration in 'YYYY-MM-DD' format"
    ] = None,
    to_date: Annotated[
        str | None, "End date for option expiration in 'YYYY-MM-DD' format"
    ] = None,
) -> str:
    """
    Returns option chain data for a specific symbol.

    Retrieves available option contracts with strike prices, expiration dates,
    and price information. This is the standard option chain function for most
    use cases. For more complex strategies, use get_advanced_option_chain().

    Parameters:
    - symbol: Underlying security symbol (e.g., 'AAPL', 'SPY')
    - contract_type: Type of option contracts to return
      - CALL: Call option contracts only
      - PUT: Put option contracts only
      - ALL: Both call and put contracts (default)
    - strike_count: Number of strikes above/below at-the-money (default: 25)
    - include_quotes: When True, includes market data for underlying and options
    - from_date: Start date for filtering by expiration ('YYYY-MM-DD')
    - to_date: End date for filtering by expiration ('YYYY-MM-DD')

    Note: Can return large datasets. Use strike_count and date parameters to
    limit the amount of data returned.
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
    Returns advanced option chain data with complex strategies and filtering.

    Use for advanced options analysis with multiple strategy types, filters, and
    theoretical pricing calculations. For basic chains, use get_option_chain().

    Parameters:
    - symbol: Underlying security symbol (e.g. 'SPY', 'AAPL')
    - contract_type: Type of options to return
      - CALL: Call option contracts only
      - PUT: Put option contracts only
      - ALL: Both call and put contracts (default)
    - strike_count: Number of strikes above/below at-the-money to return (default: 25)
    - include_quotes: When True, includes underlying and option market data
    - strategy: Option strategy to analyze
      - SINGLE: Single option contracts (default)
      - ANALYTICAL: Calculate theoretical values using volatility, etc.
      - COVERED: Covered call/put strategies
      - VERTICAL: Vertical spread strategies
      - CALENDAR: Calendar spread strategies
      - STRANGLE: Strangle strategy combinations
      - STRADDLE: Straddle strategy combinations
      - BUTTERFLY: Butterfly spread strategies
      - CONDOR: Condor spread strategies
      - DIAGONAL: Diagonal spread strategies
      - COLLAR: Collar strategy combinations
      - ROLL: Roll option positions
    - strike_range: Filter strikes by moneyness
      - IN_THE_MONEY: Only ITM options
      - NEAR_THE_MONEY: Only near-the-money options
      - OUT_OF_THE_MONEY: Only OTM options
      - STRIKES_ABOVE_MARKET: Only strikes above market
      - STRIKES_BELOW_MARKET: Only strikes below market
      - STRIKES_NEAR_MARKET: Only strikes near market
      - ALL: All available strikes (default)
    - option_type: Filter by option type
      - STANDARD: Standard options only
      - NON_STANDARD: Non-standard options only (adjusted for corporate actions)
      - ALL: All options (default)

    For ANALYTICAL strategy, add volatility, underlying_price, interest_rate,
    and days_to_expiration to calculate theoretical values.

    Note: Returns large datasets. Use strike_count and from_date/to_date to limit data.
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
    Returns option expiration dates for a symbol without contract details.

    Retrieves a list of available option expiration dates for the specified symbol.
    This is a lightweight call that's useful before requesting full option chains,
    allowing you to discover what expiration cycles are available.

    Parameters:
    - symbol: Underlying security symbol (e.g., 'AAPL', 'SPY')

    The response includes expiration dates and related information without
    individual contract details, making it more efficient than retrieving
    complete option chains when you only need expiration information.
    """
    return await call(client.get_option_expiration_chain, symbol)
