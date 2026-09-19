"""Option chain and expiration tools for the Schwab MCP server."""

import datetime
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

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


def _parse_strike_range(client: Any, strike_range: str | None) -> Any:
    """Map a descriptive strike-range name to the client's option enum.

    Args:
        client: Schwab client facade exposing option enums.
        strike_range: SDK strike-range member name, or None.

    Returns:
        The matching SDK enum member, or None when no range is provided.

    Raises:
        ValueError: If ``strike_range`` is not a valid member name.
    """
    if strike_range is None:
        return None

    enum_type = client.Options.StrikeRange
    try:
        return enum_type[strike_range]
    except KeyError as exc:
        choices = ", ".join(member.name for member in enum_type)
        raise ValueError(f"Invalid strike_range: {strike_range}. Must be one of: {choices}") from exc


async def _get_option_chain(
    client: Any,
    symbol: str,
    *,
    contract_type: Any,
    strike_count: int,
    include_underlying_quote: bool | None,
    from_date: datetime.date | str | None,
    to_date: datetime.date | str | None,
    verbose: bool,
    **advanced_kwargs: Any,
) -> JSONType:
    """Request an option chain and apply the default response shaping."""
    from_date_obj, to_date_obj = _normalize_expiration_window(
        parse_date(from_date),
        parse_date(to_date),
    )
    request_kwargs = {
        "contract_type": contract_type,
        "strike_count": strike_count,
        "include_underlying_quote": include_underlying_quote,
        "from_date": from_date_obj,
        "to_date": to_date_obj,
        **advanced_kwargs,
    }
    result = await call(client.get_option_chain, symbol, **request_kwargs)
    return result if verbose else _prune_option_chain(result)


async def get_option_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, Field(description="Underlying symbol, such as AAPL or SPY.")],
    contract_type: Annotated[
        Literal["CALL", "PUT", "ALL"] | None,
        Field(description="Option contract type: CALL, PUT, or ALL (default: ALL)."),
    ] = None,
    strike_count: Annotated[
        int,
        Field(description="Strikes above and below the at-the-money price (default: 25)."),
    ] = 25,
    include_underlying_quote: Annotated[
        bool | None,
        Field(description="Include the underlying security quote only (default: omitted)."),
    ] = None,
    from_date: Annotated[
        datetime.date | None,
        Field(
            description=(
                "First expiration date in YYYY-MM-DD format. Defaults to today when both dates are omitted. "
                "If to_date is omitted, the window ends 60 days later."
            )
        ),
    ] = None,
    to_date: Annotated[
        datetime.date | None,
        Field(
            description=(
                "Last expiration date in YYYY-MM-DD format. Defaults to today plus 60 days when both are omitted. "
                "If from_date is omitted, the window starts today or this date if earlier."
            )
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Field(description="Return full contract fields instead of the compact default (default: false)."),
    ] = False,
) -> JSONType:
    """Return standard option chain data for a symbol.

    Use ``get_option_expiration_chain`` first to discover available expirations,
    then narrow this retrieval with expiration dates and ``strike_count``.
    When both dates are omitted, the window defaults to today through the next
    60 calendar days. ``verbose=True`` returns full contract fields instead of
    the compact default.
    """
    client = ctx.options
    return await _get_option_chain(
        client,
        symbol,
        contract_type=client.Options.ContractType[contract_type] if contract_type else None,
        strike_count=strike_count,
        include_underlying_quote=include_underlying_quote,
        from_date=from_date,
        to_date=to_date,
        verbose=verbose,
    )


async def get_advanced_option_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, Field(description="Underlying symbol, such as AAPL or SPY.")],
    contract_type: Annotated[
        Literal["CALL", "PUT", "ALL"] | None,
        Field(description="Option contract type: CALL, PUT, or ALL (default: ALL)."),
    ] = None,
    strike_count: Annotated[
        int,
        Field(description="Strikes above and below the at-the-money price (default: 25)."),
    ] = 25,
    include_underlying_quote: Annotated[
        bool | None,
        Field(description="Include the underlying security quote only (default: omitted)."),
    ] = None,
    strategy: Annotated[
        Literal[
            "SINGLE",
            "ANALYTICAL",
            "COVERED",
            "VERTICAL",
            "CALENDAR",
            "STRANGLE",
            "STRADDLE",
            "BUTTERFLY",
            "CONDOR",
            "DIAGONAL",
            "COLLAR",
            "ROLL",
        ]
        | None,
        Field(
            description=(
                "Option strategy: SINGLE, ANALYTICAL, COVERED, VERTICAL, CALENDAR, STRANGLE, STRADDLE, "
                "BUTTERFLY, CONDOR, DIAGONAL, COLLAR, or ROLL (default: SINGLE)."
            )
        ),
    ] = None,
    interval: Annotated[str | None, Field(description="Strike interval for spread strategy chains.")] = None,
    strike: Annotated[float | None, Field(description="Return options only at this strike price.")] = None,
    strike_range: Annotated[
        Literal[
            "IN_THE_MONEY",
            "NEAR_THE_MONEY",
            "OUT_OF_THE_MONEY",
            "STRIKES_ABOVE_MARKET",
            "STRIKES_BELOW_MARKET",
            "STRIKES_NEAR_MARKET",
            "ALL",
        ]
        | None,
        Field(
            description=(
                "Strike range: IN_THE_MONEY, NEAR_THE_MONEY, OUT_OF_THE_MONEY, "
                "STRIKES_ABOVE_MARKET, STRIKES_BELOW_MARKET, STRIKES_NEAR_MARKET, or ALL."
            )
        ),
    ] = None,
    from_date: Annotated[
        datetime.date | None,
        Field(
            description=(
                "First expiration date in YYYY-MM-DD format. Defaults to today when both dates are omitted. "
                "If to_date is omitted, the window ends 60 days later."
            )
        ),
    ] = None,
    to_date: Annotated[
        datetime.date | None,
        Field(
            description=(
                "Last expiration date in YYYY-MM-DD format. Defaults to today plus 60 days when both are omitted. "
                "If from_date is omitted, the window starts today or this date if earlier."
            )
        ),
    ] = None,
    volatility: Annotated[float | None, Field(description="Volatility for the ANALYTICAL strategy.")] = None,
    underlying_price: Annotated[
        float | None, Field(description="Underlying price for the ANALYTICAL strategy.")
    ] = None,
    interest_rate: Annotated[float | None, Field(description="Interest rate for the ANALYTICAL strategy.")] = None,
    days_to_expiration: Annotated[
        int | None, Field(description="Days to expiration for the ANALYTICAL strategy.")
    ] = None,
    exp_month: Annotated[
        Literal[
            "JANUARY",
            "FEBRUARY",
            "MARCH",
            "APRIL",
            "MAY",
            "JUNE",
            "JULY",
            "AUGUST",
            "SEPTEMBER",
            "OCTOBER",
            "NOVEMBER",
            "DECEMBER",
            "ALL",
        ]
        | None,
        Field(description="Expiration month for ANALYTICAL: JANUARY through DECEMBER or ALL (default: ALL)."),
    ] = None,
    option_type: Annotated[
        Literal["STANDARD", "NON_STANDARD", "ALL"] | None,
        Field(description="Option type filter: STANDARD, NON_STANDARD, or ALL (default: ALL)."),
    ] = None,
    verbose: Annotated[
        bool,
        Field(description="Return full contract fields instead of the compact default (default: false)."),
    ] = False,
) -> JSONType:
    """Return advanced option chain data for strategies and analytical filters.

    Use ``get_option_expiration_chain`` first to discover available expirations,
    then narrow this retrieval with dates, strike filters, and strategy inputs.
    When both dates are omitted, the window defaults to today through the next
    60 calendar days. ``verbose=True`` returns full contract fields instead of
    the compact default.
    """
    client = ctx.options
    return await _get_option_chain(
        client,
        symbol,
        contract_type=client.Options.ContractType[contract_type] if contract_type else None,
        strike_count=strike_count,
        include_underlying_quote=include_underlying_quote,
        from_date=from_date,
        to_date=to_date,
        verbose=verbose,
        strategy=client.Options.Strategy[strategy] if strategy else None,
        interval=interval,
        strike=strike,
        strike_range=_parse_strike_range(client, strike_range),
        volatility=volatility,
        underlying_price=underlying_price,
        interest_rate=interest_rate,
        days_to_expiration=days_to_expiration,
        exp_month=client.Options.ExpirationMonth[exp_month] if exp_month else None,
        option_type=client.Options.Type[option_type] if option_type else None,
    )


async def get_option_expiration_chain(
    ctx: SchwabContext,
    symbol: Annotated[str, Field(description="Underlying symbol, such as AAPL or SPY.")],
) -> JSONType:
    """Return available option expiration dates without contract details.

    Use this lightweight discovery call before retrieving a narrowed option
    chain with ``get_option_chain`` or ``get_advanced_option_chain``.
    """
    client = ctx.options
    return await call(client.get_option_expiration_chain, symbol)


_READ_ONLY_TOOLS = (
    get_option_chain,
    get_advanced_option_chain,
    get_option_expiration_chain,
)


def register(
    server: MCPServer,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register option chain tools with the MCP server."""
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
