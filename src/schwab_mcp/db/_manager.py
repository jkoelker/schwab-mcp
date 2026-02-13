"""Database connection management for Cloud SQL PostgreSQL."""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any, Sequence

import anyio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection parameters for Cloud SQL."""

    instance_connection_name: str  # "project:region:instance"
    database: str  # "schwab_data"
    user: str  # "agent_user"
    password: str


class DatabaseManager(abc.ABC):
    """Abstract base for database operations."""

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]: ...

    @abc.abstractmethod
    async def execute_many(
        self, sql: str, params_seq: Sequence[Sequence[Any]]
    ) -> None: ...


class CloudSQLManager(DatabaseManager):
    """pg8000 via cloud-sql-python-connector, offloaded to threads."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._connector: Any = None
        self._conn: Any = None

    async def start(self) -> None:
        from google.cloud.sql.connector import Connector

        def _connect() -> tuple[Any, Any]:
            connector = Connector()
            conn = connector.connect(
                self._config.instance_connection_name,
                "pg8000",
                user=self._config.user,
                password=self._config.password,
                db=self._config.database,
            )
            return connector, conn

        self._connector, self._conn = await anyio.to_thread.run_sync(_connect)

        from schwab_mcp.db._schema import SCHEMA_SQL

        await self.execute_script(SCHEMA_SQL)
        logger.info(
            "Database connected: %s/%s",
            self._config.instance_connection_name,
            self._config.database,
        )

    async def stop(self) -> None:
        def _close() -> None:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            if self._connector is not None:
                try:
                    self._connector.close()
                except Exception:
                    pass

        await anyio.to_thread.run_sync(_close)

    async def execute_script(self, sql: str) -> None:
        """Execute multi-statement SQL (e.g. schema DDL).

        pg8000 does not support multiple statements in one ``execute()``
        call, so we split on semicolons and run each statement individually.
        """

        def _run() -> None:
            cursor = self._conn.cursor()
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            self._conn.commit()

        await anyio.to_thread.run_sync(_run)

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        return isinstance(exc, OSError) or type(exc).__name__ == "InterfaceError"

    async def _reconnect(self) -> None:
        logger.warning("Database connection lost, reconnecting…")
        try:
            await self.stop()
        except Exception:
            pass
        await self.start()

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        def _run() -> list[tuple[Any, ...]]:
            cursor = self._conn.cursor()
            cursor.execute(sql, tuple(params) if params else ())
            self._conn.commit()
            try:
                return cursor.fetchall()
            except Exception:
                return []

        try:
            return await anyio.to_thread.run_sync(_run)
        except Exception as exc:
            if not self._is_connection_error(exc):
                raise
            await self._reconnect()
            return await anyio.to_thread.run_sync(_run)

    async def execute_many(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> None:
        def _run() -> None:
            cursor = self._conn.cursor()
            for params in params_seq:
                cursor.execute(sql, tuple(params))
            self._conn.commit()

        try:
            await anyio.to_thread.run_sync(_run)
        except Exception as exc:
            if not self._is_connection_error(exc):
                raise
            await self._reconnect()
            await anyio.to_thread.run_sync(_run)


class NoOpDatabaseManager(DatabaseManager):
    """Stub when no database is configured."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        return []

    async def execute_many(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> None:
        pass
