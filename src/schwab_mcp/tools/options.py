#
from collections.abc import Callable
from typing import Annotated, Any

import datetime
from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.db._ingestion import ingest_option_chain
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call, parse_date


_EXPIRATION_WINDOW_DAYS = 60


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
) -> JSONType:
    """
    Returns option chain data (strikes, expirations, prices) for a symbol. Use for standard chains.
    Params: symbol, contract_type (CALL/PUT/ALL), strike_count (default 25), include_quotes (bool), from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
    Limit data returned using strike_count and date parameters. When both dates are omitted the tool defaults to the next 60 calendar days to avoid oversized responses.
    """
    client = ctx.options

    from_date_obj, to_date_obj = _normalize_expiration_window(
        parse_date(from_date),
        parse_date(to_date),
    )

    result = await call(
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

    snapshot_id = await ingest_option_chain(
        ctx.db,
        result,
        symbol=symbol,
        request_params={
            "contract_type": contract_type,
            "strike_count": strike_count,
            "from_date": str(from_date_obj) if from_date_obj else None,
            "to_date": str(to_date_obj) if to_date_obj else None,
        },
    )

    # When database is active, return a summary instead of full data to save context
    from schwab_mcp.db._manager import NoOpDatabaseManager

    if not isinstance(ctx.db, NoOpDatabaseManager) and isinstance(result, dict):
        # Count contracts in the response
        call_contracts = sum(
            len(contracts)
            for exp_map in (result.get("callExpDateMap") or {}).values()
            for contracts in exp_map.values()
            if isinstance(contracts, list)
        )
        put_contracts = sum(
            len(contracts)
            for exp_map in (result.get("putExpDateMap") or {}).values()
            for contracts in exp_map.values()
            if isinstance(contracts, list)
        )
        total_contracts = call_contracts + put_contracts

        storage_status = (
            f"Stored {total_contracts} contracts (snapshot_id: {snapshot_id})"
            if snapshot_id
            else f"WARNING: Failed to store to database, but fetched {total_contracts} contracts"
        )

        return {
            "status": "SUCCESS",
            "message": storage_status,
            "summary": {
                "symbol": symbol,
                "underlying_price": result.get("underlyingPrice"),
                "contracts_fetched": total_contracts,
                "calls": call_contracts,
                "puts": put_contracts,
                "snapshot_id": snapshot_id,
                "stored": snapshot_id is not None,
                "query_hint": (
                    f"Use query_stored_options(symbol='{symbol}') to retrieve specific contracts with filters"
                    if snapshot_id
                    else "Database storage failed - restart Claude to reconnect, or query was not stored"
                ),
            },
        }

    return result


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
) -> JSONType:
    """
    Returns advanced option chain data with strategies, filters, and theoretical calculations. Use for complex analysis.
    Params: symbol, contract_type, strike_count, include_quotes, strategy (SINGLE/ANALYTICAL/etc.), interval, strike, strike_range (ITM/NTM/etc.), from/to_date, volatility/underlying_price/interest_rate/days_to_expiration (for ANALYTICAL), exp_month, option_type (STANDARD/NON_STANDARD/ALL).
    Limit data returned using strike_count and date parameters. When both dates are omitted the tool defaults to the next 60 calendar days to avoid oversized responses.
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

    snapshot_id = await ingest_option_chain(
        ctx.db,
        result,
        symbol=symbol,
        request_params={
            "contract_type": contract_type,
            "strike_count": strike_count,
            "strategy": strategy,
            "strike_range": strike_range,
            "from_date": str(from_date_obj) if from_date_obj else None,
            "to_date": str(to_date_obj) if to_date_obj else None,
        },
    )

    # When database is configured, always return a summary to save context
    # Even if ingestion fails, we still provide the summary (data loss is better than context overflow)
    from schwab_mcp.db._manager import NoOpDatabaseManager

    if not isinstance(ctx.db, NoOpDatabaseManager) and isinstance(result, dict):
        # Count contracts in the response
        call_contracts = sum(
            len(contracts)
            for exp_map in (result.get("callExpDateMap") or {}).values()
            for contracts in exp_map.values()
            if isinstance(contracts, list)
        )
        put_contracts = sum(
            len(contracts)
            for exp_map in (result.get("putExpDateMap") or {}).values()
            for contracts in exp_map.values()
            if isinstance(contracts, list)
        )
        total_contracts = call_contracts + put_contracts

        storage_status = (
            f"Stored {total_contracts} contracts (snapshot_id: {snapshot_id})"
            if snapshot_id
            else f"WARNING: Failed to store to database, but fetched {total_contracts} contracts"
        )

        return {
            "status": "SUCCESS",
            "message": storage_status,
            "summary": {
                "symbol": symbol,
                "underlying_price": result.get("underlyingPrice"),
                "contracts_fetched": total_contracts,
                "calls": call_contracts,
                "puts": put_contracts,
                "snapshot_id": snapshot_id,
                "stored": snapshot_id is not None,
                "strategy": strategy,
                "query_hint": (
                    f"Use query_stored_options(symbol='{symbol}') to retrieve specific contracts with filters"
                    if snapshot_id
                    else "Database storage failed - restart Claude to reconnect, or query was not stored"
                ),
            },
        }

    return result


async def get_option_expiration_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, "Symbol of the underlying security"],
) -> JSONType:
    """
    Returns available option expiration dates for a symbol, without contract details. Lightweight call to find available cycles. Param: symbol.
    """
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
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
