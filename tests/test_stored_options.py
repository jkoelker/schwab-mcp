"""Tests for stored option chain query tools."""

from __future__ import annotations

import datetime
from typing import Any, Sequence

from schwab_mcp.db._manager import DatabaseManager, NoOpDatabaseManager
from schwab_mcp.tools.stored_options import (
    query_stored_options,
    list_option_snapshots,
    compare_option_snapshots,
)

from conftest import make_ctx, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockDatabaseManager(DatabaseManager):
    """Returns pre-configured rows and captures queries for assertion."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.last_sql: str | None = None
        self.last_params: Sequence[Any] | None = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        self.last_sql = sql
        self.last_params = params
        return self.rows

    async def execute_many(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> None:
        pass


# ---------------------------------------------------------------------------
# query_stored_options
# ---------------------------------------------------------------------------


def test_query_stored_options_noop_db():
    ctx = make_ctx(client=None, db=NoOpDatabaseManager())
    result = run(query_stored_options(ctx, "SPY"))
    assert result == {
        "error": "Database not configured. Set SCHWAB_DB_* env vars to enable."
    }


def test_query_stored_options_returns_rows():
    now = datetime.datetime(2025, 2, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [
        (
            now,
            500.0,
            "CALL",
            "SPY 250207C00500000",
            datetime.date(2025, 2, 7),
            500.0,
            5.0,
            5.5,
            5.25,
            5.25,
            1000,
            5000,
            0.5,
            0.03,
            -0.05,
            0.15,
            25.0,
        ),
    ]
    db = MockDatabaseManager(rows=rows)
    ctx = make_ctx(client=None, db=db)
    result = run(query_stored_options(ctx, "SPY"))

    assert isinstance(result, list)
    assert len(result) == 1
    row = result[0]
    assert row["fetch_timestamp"] == now.isoformat()
    assert row["underlying_price"] == 500.0
    assert row["put_call"] == "CALL"
    assert row["symbol"] == "SPY 250207C00500000"
    assert row["expiration_date"] == "2025-02-07"
    assert row["delta"] == 0.5


def test_query_stored_options_applies_filters():
    db = MockDatabaseManager(rows=[])
    ctx = make_ctx(client=None, db=db)
    run(
        query_stored_options(
            ctx,
            "SPY",
            put_call="CALL",
            expiration_date="2025-02-07",
            min_delta=0.3,
            max_delta=0.7,
            min_open_interest=100,
            min_volume=50,
            limit=10,
        )
    )

    assert db.last_sql is not None
    assert "put_call = %s" in db.last_sql
    assert "expiration_date = %s" in db.last_sql
    assert "ABS(oc.delta) >= %s" in db.last_sql
    assert "ABS(oc.delta) <= %s" in db.last_sql
    assert "open_interest >= %s" in db.last_sql
    assert "total_volume >= %s" in db.last_sql

    params = db.last_params
    assert params is not None
    assert "SPY" in params
    assert "CALL" in params
    assert "2025-02-07" in params


def test_query_stored_options_symbol_uppercased():
    db = MockDatabaseManager(rows=[])
    ctx = make_ctx(client=None, db=db)
    run(query_stored_options(ctx, "spy"))

    assert db.last_params is not None
    assert db.last_params[0] == "SPY"


# ---------------------------------------------------------------------------
# list_option_snapshots
# ---------------------------------------------------------------------------


def test_list_option_snapshots_noop_db():
    ctx = make_ctx(client=None, db=NoOpDatabaseManager())
    result = run(list_option_snapshots(ctx))
    assert result == {
        "error": "Database not configured. Set SCHWAB_DB_* env vars to enable."
    }


def test_list_option_snapshots_with_symbol():
    now = datetime.datetime(2025, 2, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [
        (1, now, "SPY", 500.0, 100, "SINGLE", "SUCCESS"),
    ]
    db = MockDatabaseManager(rows=rows)
    ctx = make_ctx(client=None, db=db)
    result = run(list_option_snapshots(ctx, symbol="spy"))

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["snapshot_id"] == 1
    assert result[0]["symbol"] == "SPY"
    assert result[0]["fetch_timestamp"] == now.isoformat()

    assert db.last_params is not None
    assert "SPY" in db.last_params


def test_list_option_snapshots_no_symbol():
    db = MockDatabaseManager(rows=[])
    ctx = make_ctx(client=None, db=db)
    run(list_option_snapshots(ctx))

    assert db.last_sql is not None
    assert "WHERE" not in db.last_sql


# ---------------------------------------------------------------------------
# compare_option_snapshots
# ---------------------------------------------------------------------------


def test_compare_option_snapshots_noop_db():
    ctx = make_ctx(client=None, db=NoOpDatabaseManager())
    result = run(compare_option_snapshots(ctx, "SPY 250207C00500000"))
    assert result == {
        "error": "Database not configured. Set SCHWAB_DB_* env vars to enable."
    }


def test_compare_option_snapshots_returns_rows():
    now = datetime.datetime(2025, 2, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)
    rows = [
        (
            now,
            500.0,
            5.0,
            5.5,
            5.25,
            5.25,
            1000,
            5000,
            0.5,
            0.03,
            -0.05,
            0.15,
            25.0,
            5.25,
            0.0,
        ),
    ]
    db = MockDatabaseManager(rows=rows)
    ctx = make_ctx(client=None, db=db)
    result = run(compare_option_snapshots(ctx, "SPY 250207C00500000"))

    assert isinstance(result, list)
    assert len(result) == 1
    row = result[0]
    assert row["fetch_timestamp"] == now.isoformat()
    assert row["underlying_price"] == 500.0
    assert row["bid"] == 5.0
    assert row["time_value"] == 5.25
    assert row["intrinsic_value"] == 0.0


def test_compare_option_snapshots_passes_symbol_and_limit():
    db = MockDatabaseManager(rows=[])
    ctx = make_ctx(client=None, db=db)
    run(compare_option_snapshots(ctx, "AAPL 250321C00200000", limit=5))

    assert db.last_params is not None
    assert db.last_params[0] == "AAPL 250321C00200000"
    assert db.last_params[1] == 5
