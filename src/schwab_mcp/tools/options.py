"""Option chain and expiration tools for the Schwab MCP server."""

import datetime
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call, parse_date

_EXPIRATION_WINDOW_DAYS = 60

_COMPACT_CONTRACT_FIELDS = frozenset(
    {
        "strike",
        "bid",
        "ask",
        "last",
        "mark",
        "bidSize",
        "askSize",
        "volume",
        "openInterest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "impliedVolatility",
        "inTheMoney",
        "expirationDate",
        "daysToExpiration",
        "expirationType",
    }
)


def _prune_contract(contract: dict[str, JSONType]) -> dict[str, JSONType]:
    return {k: v for k, v in contract.items() if k in _COMPACT_CONTRACT_FIELDS}


def _prune_option_chain(payload: JSONType) -> JSONType:
    """Prune contract fields in-place. Safe because ``call()`` always returns
    a freshly-parsed JSON object with no other references.
    """
    if not isinstance(payload, dict):
        return payload
    for map_key in ("callExpDateMap", "putExpDateMap"):
        exp_map = payload.get(map_key)
        if not isinstance(exp_map, dict):
            continue
        for strikes in exp_map.values():
            if not isinstance(strikes, dict):
                continue
            for strike_key, contracts in strikes.items():
                if not isinstance(contracts, list):
                    continue
                strikes[strike_key] = [_prune_contract(c) if isinstance(c, dict) else c for c in contracts]
    return payload


def _normalize_expiration_window(
    from_date: datetime.date | None,
    to_date: datetime.date | None,
    *,
    today: datetime.date | None = None,
) -> tuple[datetime.date | None, datetime.date | None]:
    if from_date is None and to_date is None:
        today = datetime.date.today() if today is None else today
        return today, today + datetime.timedelta(days=_EXPIRATION_WINDOW_DAYS)

    if from_date is None and to_date is not None:
        today = datetime.date.today() if today is None else today
        from_date = min(today, to_date)

    if from_date is not None and to_date is None:
        to_date = from_date + datetime.timedelta(days=_EXPIRATION_WINDOW_DAYS)

    if from_date is not None and to_date is not None and to_date < from_date:
        to_date = from_date

    return from_date, to_date


async def get_option_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security (e.g., 'AAPL', 'SPY')"],
    contract_type: Annotated[str | None, "Type of option contracts: CALL, PUT, or ALL (default)"] = None,
    strike_count: Annotated[
        int,
        "Number of strikes above/below the at-the-money price (default: 25)",
    ] = 25,
    include_quotes: Annotated[bool | None, "Include underlying and option market quotes"] = None,
    from_date: Annotated[
        str | datetime.date | None,
        "Start date for option expiration ('YYYY-MM-DD' or datetime.date)",
    ] = None,
    to_date: Annotated[
        str | datetime.date | None,
        "End date for option expiration ('YYYY-MM-DD' or datetime.date)",
    ] = None,
    verbose: Annotated[
        bool,
        "Return all raw contract fields instead of the compact default. Compact mode keeps price/greeks/liquidity fields only.",
    ] = False,
) -> JSONType:
    """Returns option chain data (strikes, expirations, prices) for a symbol. Use for standard chains.
    Params: symbol, contract_type (CALL/PUT/ALL), strike_count (default 25), include_quotes (bool), from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
    Limit data returned using strike_count and date parameters. When both dates are omitted the tool defaults to the next 60 calendar days to avoid oversized responses.
    By default returns compact per-contract fields only; pass verbose=True for the full raw payload.
    """
    client = ctx.options

    from_date_obj, to_date_obj = _normalize_expiration_window(
        parse_date(from_date),
        parse_date(to_date),
    )

    result = await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type.upper()] if contract_type else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        from_date=from_date_obj,
        to_date=to_date_obj,
    )
    return result if verbose else _prune_option_chain(result)


async def get_advanced_option_chain(
    ctx: SchwabContext,
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
    interval: Annotated[str | None, "Strike interval for spread strategy chains"] = None,
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
    underlying_price: Annotated[float | None, "Underlying price for ANALYTICAL strategy"] = None,
    interest_rate: Annotated[float | None, "Interest rate for ANALYTICAL strategy"] = None,
    days_to_expiration: Annotated[int | None, "Days to expiration for ANALYTICAL strategy"] = None,
    exp_month: Annotated[str | None, "Expiration month (e.g., JAN) for ANALYTICAL strategy"] = None,
    option_type: Annotated[str | None, "Filter option type: STANDARD, NON_STANDARD, ALL (default)"] = None,
    verbose: Annotated[
        bool,
        "Return all raw contract fields instead of the compact default. Compact mode keeps price/greeks/liquidity fields only.",
    ] = False,
) -> JSONType:
    """Returns advanced option chain data with strategies, filters, and theoretical calculations. Use for complex analysis.
    Params: symbol, contract_type, strike_count, include_quotes, strategy (SINGLE/ANALYTICAL/etc.), interval, strike, strike_range (ITM/NTM/etc.), from/to_date, volatility/underlying_price/interest_rate/days_to_expiration (for ANALYTICAL), exp_month, option_type (STANDARD/NON_STANDARD/ALL).
    Limit data returned using strike_count and date parameters. When both dates are omitted the tool defaults to the next 60 calendar days to avoid oversized responses.
    By default returns compact per-contract fields only; pass verbose=True for the full raw payload.
    """
    client = ctx.options

    from_date_obj = parse_date(from_date)
    to_date_obj = parse_date(to_date)
    from_date_obj, to_date_obj = _normalize_expiration_window(
        from_date_obj,
        to_date_obj,
    )

    result = await call(
        client.get_option_chain,
        symbol,
        contract_type=client.Options.ContractType[contract_type.upper()] if contract_type else None,
        strike_count=strike_count,
        include_underlying_quote=include_quotes,
        strategy=client.Options.Strategy[strategy.upper()] if strategy else None,
        interval=interval,
        strike=strike,
        strike_range=client.Options.StrikeRange[strike_range.upper()] if strike_range else None,
        from_date=from_date_obj,
        to_date=to_date_obj,
        volatility=volatility,
        underlying_price=underlying_price,
        interest_rate=interest_rate,
        days_to_expiration=days_to_expiration,
        exp_month=client.Options.ExpirationMonth[exp_month.upper()] if exp_month else None,
        option_type=client.Options.Type[option_type.upper()] if option_type else None,
    )
    return result if verbose else _prune_option_chain(result)


async def get_option_expiration_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security"],
) -> JSONType:
    """Returns available option expiration dates for a symbol, without contract details. Lightweight call to find available cycles. Param: symbol."""
    client = ctx.options
    return await call(client.get_option_expiration_chain, symbol)


_READ_ONLY_TOOLS = (
    get_option_chain,
    get_advanced_option_chain,
    get_option_expiration_chain,
)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register option chain tools with the MCP server."""
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
