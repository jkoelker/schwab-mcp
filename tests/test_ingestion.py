"""Tests for option chain ingestion into the database."""

from __future__ import annotations

import datetime
import json
from typing import Any, Sequence

from schwab_mcp.db._manager import DatabaseManager, NoOpDatabaseManager
from schwab_mcp.db._ingestion import (
    ingest_option_chain,
    _parse_exp_date,
    _epoch_ms_to_datetime,
)

from conftest import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CapturingDatabaseManager(DatabaseManager):
    """Records all execute/execute_many calls for assertions."""

    def __init__(self, execute_return: list[tuple[Any, ...]] | None = None) -> None:
        self.execute_calls: list[tuple[str, Sequence[Any]]] = []
        self.execute_many_calls: list[tuple[str, Sequence[Sequence[Any]]]] = []
        self._execute_return = execute_return or [(1,)]

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        self.execute_calls.append((sql, params))
        return self._execute_return

    async def execute_many(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> None:
        self.execute_many_calls.append((sql, list(params_seq)))


def _make_chain(
    *,
    call_map: dict[str, Any] | None = None,
    put_map: dict[str, Any] | None = None,
    underlying_price: float = 500.0,
) -> dict[str, Any]:
    """Build a minimal Schwab-style option chain response dict."""
    data: dict[str, Any] = {
        "strategy": "SINGLE",
        "isDelayed": False,
        "isIndex": False,
        "interestRate": 0.05,
        "underlyingPrice": underlying_price,
        "volatility": 20.0,
        "daysToExpiration": 0.0,
        "dividendYield": 0.0,
        "numberOfContracts": 10,
        "status": "SUCCESS",
    }
    if call_map is not None:
        data["callExpDateMap"] = call_map
    if put_map is not None:
        data["putExpDateMap"] = put_map
    return data


def _make_contract(**overrides: Any) -> dict[str, Any]:
    """Build a minimal contract dict."""
    base: dict[str, Any] = {
        "putCall": "CALL",
        "symbol": "SPY 250207C00500000",
        "description": "SPY call",
        "exchangeName": "CBOE",
        "daysToExpiration": 30,
        "strikePrice": 500.0,
        "bid": 5.0,
        "ask": 5.50,
        "last": 5.25,
        "mark": 5.25,
        "bidSize": 10,
        "askSize": 10,
        "lastSize": 5,
        "highPrice": 6.0,
        "lowPrice": 4.0,
        "openPrice": 4.5,
        "closePrice": 5.0,
        "netChange": 0.25,
        "totalVolume": 1000,
        "volatility": 25.0,
        "delta": 0.5,
        "gamma": 0.03,
        "theta": -0.05,
        "vega": 0.15,
        "rho": 0.01,
        "openInterest": 5000,
        "timeValue": 5.25,
        "theoreticalOptionValue": 5.20,
        "theoreticalVolatility": 24.5,
        "quoteTimeInLong": 1707300000000,
        "tradeTimeInLong": 1707300000000,
        "inTheMoney": True,
        "mini": False,
        "nonStandard": False,
        "pennyPilot": True,
        "intrinsicValue": 0.0,
        "expirationType": "R",
        "multiplier": 100.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests: _parse_exp_date
# ---------------------------------------------------------------------------


def test_parse_exp_date_normal():
    assert _parse_exp_date("2025-02-07:36") == datetime.date(2025, 2, 7)


def test_parse_exp_date_no_suffix():
    assert _parse_exp_date("2025-12-31") == datetime.date(2025, 12, 31)


def test_parse_exp_date_invalid():
    assert _parse_exp_date("not-a-date:5") is None


def test_parse_exp_date_empty():
    assert _parse_exp_date("") is None


# ---------------------------------------------------------------------------
# Tests: _epoch_ms_to_datetime
# ---------------------------------------------------------------------------


def test_epoch_ms_to_datetime_normal():
    result = _epoch_ms_to_datetime(1707300000000)
    assert isinstance(result, datetime.datetime)
    assert result.tzinfo == datetime.timezone.utc


def test_epoch_ms_to_datetime_none():
    assert _epoch_ms_to_datetime(None) is None


def test_epoch_ms_to_datetime_zero():
    assert _epoch_ms_to_datetime(0) is None


# ---------------------------------------------------------------------------
# Tests: NoOp short-circuits
# ---------------------------------------------------------------------------


def test_noop_db_short_circuits():
    db = NoOpDatabaseManager()
    run(ingest_option_chain(db, {"key": "value"}, symbol="SPY"))
    # No error, no calls


def test_non_dict_data_returns_immediately():
    db = CapturingDatabaseManager()
    run(ingest_option_chain(db, "not a dict", symbol="SPY"))
    assert len(db.execute_calls) == 0


# ---------------------------------------------------------------------------
# Tests: successful ingestion
# ---------------------------------------------------------------------------


def test_ingest_single_call_contract():
    db = CapturingDatabaseManager(execute_return=[(42,)])
    chain = _make_chain(
        call_map={
            "2025-02-07:36": {
                "500.0": [_make_contract()],
            },
        },
    )
    run(
        ingest_option_chain(
            db, chain, symbol="SPY", request_params={"strike_count": 25}
        )
    )

    # Should have 1 execute (INSERT snapshot RETURNING id) and 1 execute_many (contracts)
    assert len(db.execute_calls) == 1
    assert "option_chain_snapshots" in db.execute_calls[0][0]
    snapshot_params = db.execute_calls[0][1]
    assert snapshot_params[0] == "SPY"
    assert snapshot_params[1] == "SINGLE"  # strategy
    # request_params should be JSON
    assert json.loads(snapshot_params[-1]) == {"strike_count": 25}

    assert len(db.execute_many_calls) == 1
    sql, rows = db.execute_many_calls[0]
    assert "option_contracts" in sql
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 42  # snapshot_id
    assert row[1] == "CALL"  # put_call
    assert row[2] == "SPY 250207C00500000"  # symbol


def test_ingest_both_call_and_put_maps():
    db = CapturingDatabaseManager(execute_return=[(7,)])
    chain = _make_chain(
        call_map={
            "2025-03-21:44": {"500.0": [_make_contract(putCall="CALL")]},
        },
        put_map={
            "2025-03-21:44": {"500.0": [_make_contract(putCall="PUT")]},
        },
    )
    run(ingest_option_chain(db, chain, symbol="SPY"))

    assert len(db.execute_many_calls) == 1
    rows = db.execute_many_calls[0][1]
    assert len(rows) == 2
    put_calls = {r[1] for r in rows}
    assert put_calls == {"CALL", "PUT"}


def test_ingest_multiple_strikes_and_expirations():
    db = CapturingDatabaseManager(execute_return=[(99,)])
    chain = _make_chain(
        call_map={
            "2025-02-07:36": {
                "500.0": [_make_contract(strikePrice=500.0)],
                "510.0": [_make_contract(strikePrice=510.0)],
            },
            "2025-02-14:43": {
                "500.0": [_make_contract(strikePrice=500.0)],
            },
        },
    )
    run(ingest_option_chain(db, chain, symbol="SPY"))

    rows = db.execute_many_calls[0][1]
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Tests: empty / edge cases
# ---------------------------------------------------------------------------


def test_ingest_empty_exp_date_maps():
    db = CapturingDatabaseManager(execute_return=[(1,)])
    chain = _make_chain(call_map={}, put_map={})
    run(ingest_option_chain(db, chain, symbol="SPY"))

    # Snapshot row inserted, but no execute_many since no contracts
    assert len(db.execute_calls) == 1
    assert len(db.execute_many_calls) == 0


def test_ingest_missing_exp_date_maps():
    db = CapturingDatabaseManager(execute_return=[(1,)])
    chain = _make_chain()  # no call_map or put_map
    run(ingest_option_chain(db, chain, symbol="SPY"))

    assert len(db.execute_calls) == 1
    assert len(db.execute_many_calls) == 0


def test_ingest_malformed_contract_skipped():
    db = CapturingDatabaseManager(execute_return=[(1,)])
    chain = _make_chain(
        call_map={
            "2025-02-07:36": {
                "500.0": [
                    "not a dict",
                    _make_contract(),
                ],
            },
        },
    )
    run(ingest_option_chain(db, chain, symbol="SPY"))

    rows = db.execute_many_calls[0][1]
    assert len(rows) == 1  # only the valid contract


def test_ingest_malformed_strikes_skipped():
    db = CapturingDatabaseManager(execute_return=[(1,)])
    chain = _make_chain(
        call_map={
            "2025-02-07:36": "not a dict",
        },
    )
    run(ingest_option_chain(db, chain, symbol="SPY"))

    assert len(db.execute_many_calls) == 0


# ---------------------------------------------------------------------------
# Tests: failure isolation
# ---------------------------------------------------------------------------


def test_ingest_failure_does_not_propagate():
    """If the DB execute raises, ingest_option_chain catches it."""

    class FailingDB(DatabaseManager):
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def execute(
            self, sql: str, params: Sequence[Any] = ()
        ) -> list[tuple[Any, ...]]:
            raise RuntimeError("DB is down")

        async def execute_many(
            self, sql: str, params_seq: Sequence[Sequence[Any]]
        ) -> None:
            raise RuntimeError("DB is down")

    db = FailingDB()
    chain = _make_chain(call_map={"2025-02-07:36": {"500.0": [_make_contract()]}})
    # This should NOT raise
    run(ingest_option_chain(db, chain, symbol="SPY"))


def test_ingest_no_request_params():
    db = CapturingDatabaseManager(execute_return=[(1,)])
    chain = _make_chain(
        call_map={"2025-02-07:36": {"500.0": [_make_contract()]}},
    )
    run(ingest_option_chain(db, chain, symbol="SPY", request_params=None))

    snapshot_params = db.execute_calls[0][1]
    # Last param should be None (no request_params JSON)
    assert snapshot_params[-1] is None
