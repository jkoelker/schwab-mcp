"""MCP tools for querying stored option chain data."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.db._manager import NoOpDatabaseManager
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType


async def query_stored_options(
    ctx: SchwabContext,
    symbol: Annotated[str, "Underlying symbol to query (e.g., 'SPY')"],
    put_call: Annotated[str | None, "Filter by CALL or PUT"] = None,
    strike_price: Annotated[float | None, "Filter by exact strike price"] = None,
    min_strike: Annotated[float | None, "Minimum strike price"] = None,
    max_strike: Annotated[float | None, "Maximum strike price"] = None,
    expiration_date: Annotated[
        str | None, "Filter by expiration date (YYYY-MM-DD)"
    ] = None,
    min_delta: Annotated[float | None, "Minimum absolute delta"] = None,
    max_delta: Annotated[float | None, "Maximum absolute delta"] = None,
    min_open_interest: Annotated[int | None, "Minimum open interest"] = None,
    min_volume: Annotated[int | None, "Minimum total volume"] = None,
    limit: Annotated[int, "Max rows to return (default 50)"] = 50,
) -> JSONType:
    """Query stored option chain data from the database.

    Returns the most recent snapshot's option contracts with greeks, pricing,
    and volume data. Data is stored automatically when get_option_chain or
    get_advanced_option_chain is called.
    """
    if isinstance(ctx.db, NoOpDatabaseManager):
        return {"error": "Database not configured. Set SCHWAB_DB_* env vars to enable."}

    conditions = ["oc.underlying_symbol = %s"]
    params: list[Any] = [symbol.upper()]

    if put_call:
        conditions.append("oc.put_call = %s")
        params.append(put_call.upper())
    if strike_price is not None:
        conditions.append("oc.strike_price = %s")
        params.append(strike_price)
    if min_strike is not None:
        conditions.append("oc.strike_price >= %s")
        params.append(min_strike)
    if max_strike is not None:
        conditions.append("oc.strike_price <= %s")
        params.append(max_strike)
    if expiration_date:
        conditions.append("oc.expiration_date = %s")
        params.append(expiration_date)
    if min_delta is not None:
        conditions.append("ABS(oc.delta) >= %s")
        params.append(min_delta)
    if max_delta is not None:
        conditions.append("ABS(oc.delta) <= %s")
        params.append(max_delta)
    if min_open_interest is not None:
        conditions.append("oc.open_interest >= %s")
        params.append(min_open_interest)
    if min_volume is not None:
        conditions.append("oc.total_volume >= %s")
        params.append(min_volume)

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await ctx.db.execute(
        f"""
        SELECT s.fetch_timestamp, s.underlying_price,
               oc.put_call, oc.symbol, oc.expiration_date, oc.strike_price,
               oc.bid, oc.ask, oc.last, oc.mark, oc.total_volume, oc.open_interest,
               oc.delta, oc.gamma, oc.theta, oc.vega, oc.volatility
        FROM option_contracts oc
        JOIN option_chain_snapshots s ON s.id = oc.snapshot_id
        WHERE {where}
        ORDER BY s.fetch_timestamp DESC, oc.expiration_date, oc.strike_price
        LIMIT %s
        """,
        params,
    )

    columns = [
        "fetch_timestamp",
        "underlying_price",
        "put_call",
        "symbol",
        "expiration_date",
        "strike_price",
        "bid",
        "ask",
        "last",
        "mark",
        "total_volume",
        "open_interest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "volatility",
    ]
    return [dict(zip(columns, _serialize_row(row))) for row in rows]


async def list_option_snapshots(
    ctx: SchwabContext,
    symbol: Annotated[str | None, "Filter by underlying symbol"] = None,
    limit: Annotated[int, "Max snapshots to return (default 20)"] = 20,
) -> JSONType:
    """List stored option chain snapshots with metadata.

    Shows when data was fetched, how many contracts were in each snapshot,
    and underlying price at fetch time.
    """
    if isinstance(ctx.db, NoOpDatabaseManager):
        return {"error": "Database not configured. Set SCHWAB_DB_* env vars to enable."}

    if symbol:
        rows = await ctx.db.execute(
            """
            SELECT s.id, s.fetch_timestamp, s.symbol, s.underlying_price,
                   s.number_of_contracts, s.strategy, s.status
            FROM option_chain_snapshots s
            WHERE s.symbol = %s
            ORDER BY s.fetch_timestamp DESC
            LIMIT %s
            """,
            (symbol.upper(), limit),
        )
    else:
        rows = await ctx.db.execute(
            """
            SELECT s.id, s.fetch_timestamp, s.symbol, s.underlying_price,
                   s.number_of_contracts, s.strategy, s.status
            FROM option_chain_snapshots s
            ORDER BY s.fetch_timestamp DESC
            LIMIT %s
            """,
            (limit,),
        )

    columns = [
        "snapshot_id",
        "fetch_timestamp",
        "symbol",
        "underlying_price",
        "number_of_contracts",
        "strategy",
        "status",
    ]
    return [dict(zip(columns, _serialize_row(row))) for row in rows]


async def compare_option_snapshots(
    ctx: SchwabContext,
    symbol: Annotated[str, "Option contract symbol (e.g., 'SPY 250207C00500000')"],
    limit: Annotated[int, "Number of historical data points (default 10)"] = 10,
) -> JSONType:
    """Compare an option contract across multiple snapshots over time.

    Shows how bid/ask/mark, delta, theta, volatility, and open interest have
    changed for a specific option symbol.
    """
    if isinstance(ctx.db, NoOpDatabaseManager):
        return {"error": "Database not configured. Set SCHWAB_DB_* env vars to enable."}

    rows = await ctx.db.execute(
        """
        SELECT s.fetch_timestamp, s.underlying_price,
               oc.bid, oc.ask, oc.last, oc.mark, oc.total_volume, oc.open_interest,
               oc.delta, oc.gamma, oc.theta, oc.vega, oc.volatility,
               oc.time_value, oc.intrinsic_value
        FROM option_contracts oc
        JOIN option_chain_snapshots s ON s.id = oc.snapshot_id
        WHERE oc.symbol = %s
        ORDER BY s.fetch_timestamp DESC
        LIMIT %s
        """,
        (symbol, limit),
    )

    columns = [
        "fetch_timestamp",
        "underlying_price",
        "bid",
        "ask",
        "last",
        "mark",
        "total_volume",
        "open_interest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "volatility",
        "time_value",
        "intrinsic_value",
    ]
    return [dict(zip(columns, _serialize_row(row))) for row in rows]


def _serialize_row(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """Convert non-JSON-serializable values to strings."""
    result: list[Any] = []
    for val in row:
        if isinstance(val, (datetime.datetime, datetime.date)):
            result.append(val.isoformat())
        else:
            result.append(val)
    return tuple(result)


_READ_ONLY_TOOLS = (
    query_stored_options,
    list_option_snapshots,
    compare_option_snapshots,
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
