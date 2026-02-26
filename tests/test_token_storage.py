from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Sequence

import pytest

from schwab_mcp.db import DatabaseManager
from schwab_mcp.remote.token_storage import PostgresTokenStorage


class FakeDatabaseManager(DatabaseManager):
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        self.executed.append((sql, tuple(params)))
        if sql.strip().startswith("SELECT token_data"):
            key = params[0] if params else "default"
            if key in self.rows:
                return [(self.rows[key],)]
            return []
        if sql.strip().startswith("SELECT 1"):
            key = params[0] if params else "default"
            if key in self.rows:
                return [(1,)]
            return []
        if sql.strip().startswith("INSERT"):
            key = params[0]
            self.rows[key] = json.loads(params[1])
        return []

    async def execute_many(
        self, sql: str, params_seq: Sequence[Sequence[Any]]
    ) -> None:
        pass


def run(coro: Any) -> Any:
    return asyncio.run(coro)


SAMPLE_TOKEN: dict[str, Any] = {
    "access_token": "test_access",
    "refresh_token": "test_refresh",
    "token_type": "Bearer",
    "expires_in": 1800,
}


class TestPostgresTokenStorage:
    def test_ensure_table_executes_ddl(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        run(storage.ensure_table())

        assert len(db.executed) == 1
        sql = db.executed[0][0]
        assert "CREATE TABLE" in sql
        assert "schwab_tokens" in sql

    def test_load_sync_returns_cached_token(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)
        storage._cached_token = SAMPLE_TOKEN

        result = storage.load()

        assert result == SAMPLE_TOKEN

    def test_load_sync_raises_when_no_cache(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        with pytest.raises(FileNotFoundError):
            storage.load()

    def test_load_async_returns_from_db(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = SAMPLE_TOKEN
        storage = PostgresTokenStorage(db)

        result = run(storage.load_async())

        assert result == SAMPLE_TOKEN
        assert storage._cached_token == SAMPLE_TOKEN

    def test_load_async_returns_cached_when_fresh(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = {"access_token": "from_db"}
        storage = PostgresTokenStorage(db)
        storage._cached_token = SAMPLE_TOKEN
        storage._cache_time = time.time()

        result = run(storage.load_async())

        assert result == SAMPLE_TOKEN
        assert len(db.executed) == 0

    def test_load_async_refreshes_stale_cache(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = {"access_token": "fresh_from_db"}
        storage = PostgresTokenStorage(db, cache_ttl=10)
        storage._cached_token = SAMPLE_TOKEN
        storage._cache_time = time.time() - 20

        result = run(storage.load_async())

        assert result == {"access_token": "fresh_from_db"}
        assert storage._cached_token == {"access_token": "fresh_from_db"}

    def test_load_async_raises_when_not_in_db(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        with pytest.raises(FileNotFoundError, match="not found"):
            run(storage.load_async())

    def test_load_async_parses_string_json(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = json.dumps(SAMPLE_TOKEN)  # type: ignore[assignment]
        storage = PostgresTokenStorage(db)

        result = run(storage.load_async())

        assert result == SAMPLE_TOKEN

    def test_load_async_raises_on_non_dict(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = json.dumps([1, 2, 3])  # type: ignore[assignment]
        storage = PostgresTokenStorage(db)

        with pytest.raises(ValueError, match="not a valid dictionary"):
            run(storage.load_async())

    def test_write_async_upserts_to_db(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        run(storage.write_async(SAMPLE_TOKEN))

        insert_calls = [
            (sql, params) for sql, params in db.executed if "INSERT" in sql
        ]
        assert len(insert_calls) == 1
        assert "ON CONFLICT" in insert_calls[0][0]
        assert storage._cached_token == SAMPLE_TOKEN
        assert db.rows["default"] == SAMPLE_TOKEN

    def test_write_async_skips_empty_token(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        run(storage.write_async({}))

        assert len(db.executed) == 0
        assert storage._cached_token is None

    def test_write_sync_updates_cache(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        storage.write(SAMPLE_TOKEN)

        assert storage._cached_token == SAMPLE_TOKEN

    def test_write_sync_skips_empty_token(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        storage.write({})

        assert storage._cached_token is None

    def test_exists_sync_checks_cache(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        assert storage.exists() is False

        storage._cached_token = SAMPLE_TOKEN

        assert storage.exists() is True

    def test_exists_async_queries_db(self) -> None:
        db = FakeDatabaseManager()
        storage = PostgresTokenStorage(db)

        assert run(storage.exists_async()) is False

        db.rows["default"] = SAMPLE_TOKEN

        assert run(storage.exists_async()) is True

    def test_invalidate_cache_clears_state(self) -> None:
        db = FakeDatabaseManager()
        db.rows["default"] = {"access_token": "from_db"}
        storage = PostgresTokenStorage(db)

        run(storage.load_async())
        assert storage._cached_token is not None

        storage.invalidate_cache()

        assert storage._cached_token is None
        assert storage._cache_time == 0.0

        result = run(storage.load_async())
        assert result == {"access_token": "from_db"}
        select_calls = [
            (sql, params) for sql, params in db.executed if "SELECT token_data" in sql
        ]
        assert len(select_calls) == 2

    def test_custom_key(self) -> None:
        db = FakeDatabaseManager()
        db.rows["user-42"] = SAMPLE_TOKEN
        storage = PostgresTokenStorage(db, key="user-42")

        result = run(storage.load_async())

        assert result == SAMPLE_TOKEN
        select_calls = [
            (sql, params) for sql, params in db.executed if "SELECT" in sql
        ]
        assert select_calls[0][1] == ("user-42",)
