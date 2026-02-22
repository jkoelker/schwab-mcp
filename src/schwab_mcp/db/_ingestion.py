"""Parse and store Schwab option chain responses."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from schwab_mcp.db._manager import DatabaseManager, NoOpDatabaseManager

logger = logging.getLogger(__name__)


async def ingest_option_chain(
    db: DatabaseManager,
    data: Any,
    *,
    symbol: str,
    request_params: dict[str, Any] | None = None,
) -> int | None:
    """Store an option chain response in the database.

    Returns the snapshot_id if successfully stored, None otherwise.

    Fail-safe: all exceptions are caught and logged so the calling tool
    always succeeds even if storage fails.
    """
    if isinstance(db, NoOpDatabaseManager):
        return None
    if not isinstance(data, dict):
        return None

    try:
        return await _do_ingest(db, data, symbol=symbol, request_params=request_params)
    except Exception:
        logger.exception("Failed to ingest option chain for %s", symbol)
        return None


async def _do_ingest(
    db: DatabaseManager,
    data: dict[str, Any],
    *,
    symbol: str,
    request_params: dict[str, Any] | None,
) -> int:
    snapshot_rows = await db.execute(
        """
        INSERT INTO option_chain_snapshots
            (symbol, strategy, is_delayed, is_index, interest_rate,
             underlying_price, volatility, days_to_expiration,
             dividend_yield, number_of_contracts, status, request_params)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            symbol,
            data.get("strategy"),
            data.get("isDelayed"),
            data.get("isIndex"),
            data.get("interestRate"),
            data.get("underlyingPrice"),
            data.get("volatility"),
            data.get("daysToExpiration"),
            data.get("dividendYield"),
            data.get("numberOfContracts"),
            data.get("status"),
            json.dumps(request_params) if request_params else None,
        ),
    )

    snapshot_id = snapshot_rows[0][0]

    contract_rows: list[tuple[Any, ...]] = []
    for map_key in ("callExpDateMap", "putExpDateMap"):
        exp_date_map = data.get(map_key)
        if not isinstance(exp_date_map, dict):
            continue

        for exp_date_str, strikes in exp_date_map.items():
            exp_date = _parse_exp_date(exp_date_str)
            if not isinstance(strikes, dict):
                continue

            for _strike_str, contracts in strikes.items():
                if not isinstance(contracts, list):
                    continue

                for contract in contracts:
                    if not isinstance(contract, dict):
                        continue
                    contract_rows.append(
                        _contract_to_row(snapshot_id, symbol, exp_date, contract)
                    )

    if contract_rows:
        await db.execute_many(_INSERT_CONTRACT_SQL, contract_rows)

    logger.info(
        "Ingested %d contracts for %s (snapshot_id=%d)",
        len(contract_rows),
        symbol,
        snapshot_id,
    )

    return snapshot_id


def _parse_exp_date(exp_date_str: str) -> datetime.date | None:
    """Parse '2025-02-07:36' to a date object."""
    try:
        date_part = exp_date_str.split(":")[0]
        return datetime.date.fromisoformat(date_part)
    except (ValueError, IndexError):
        return None


def _epoch_ms_to_datetime(ms: int | float | None) -> datetime.datetime | None:
    """Convert epoch milliseconds to a UTC datetime."""
    if ms is None or ms == 0:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


def _contract_to_row(
    snapshot_id: int,
    underlying_symbol: str,
    exp_date: datetime.date | None,
    c: dict[str, Any],
) -> tuple[Any, ...]:
    """Extract a flat tuple from a contract dict for batch insert."""
    return (
        snapshot_id,
        c.get("putCall"),
        c.get("symbol"),
        c.get("description"),
        c.get("exchangeName"),
        underlying_symbol,
        exp_date,
        c.get("daysToExpiration"),
        c.get("strikePrice"),
        c.get("bid"),
        c.get("ask"),
        c.get("last"),
        c.get("mark"),
        c.get("bidSize"),
        c.get("askSize"),
        c.get("lastSize"),
        c.get("highPrice"),
        c.get("lowPrice"),
        c.get("openPrice"),
        c.get("closePrice"),
        c.get("netChange"),
        c.get("totalVolume"),
        c.get("volatility"),
        c.get("delta"),
        c.get("gamma"),
        c.get("theta"),
        c.get("vega"),
        c.get("rho"),
        c.get("openInterest"),
        c.get("timeValue"),
        c.get("theoreticalOptionValue"),
        c.get("theoreticalVolatility"),
        _epoch_ms_to_datetime(c.get("quoteTimeInLong")),
        _epoch_ms_to_datetime(c.get("tradeTimeInLong")),
        c.get("inTheMoney"),
        c.get("mini"),
        c.get("nonStandard"),
        c.get("pennyPilot"),
        c.get("intrinsicValue"),
        c.get("expirationType"),
        c.get("multiplier"),
    )


_INSERT_CONTRACT_SQL = """
    INSERT INTO option_contracts
        (snapshot_id, put_call, symbol, description, exchange_name,
         underlying_symbol, expiration_date, days_to_expiration, strike_price,
         bid, ask, last, mark, bid_size, ask_size, last_size,
         high_price, low_price, open_price, close_price, net_change,
         total_volume, volatility, delta, gamma, theta, vega, rho,
         open_interest, time_value, theoretical_option_value,
         theoretical_volatility, quote_time, trade_time,
         in_the_money, mini, non_standard, penny_pilot,
         intrinsic_value, expiration_type, multiplier)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
