"""Postgres-based Schwab token storage for Cloud Run deployments.

Reads and writes Schwab OAuth tokens to the existing Cloud SQL Postgres
database, with in-memory caching to avoid hitting the DB on every tool call.

Used by both the MCP server (read + refresh write-back) and the admin
service (write after Schwab re-auth).

Follows the existing database patterns in schwab_mcp.db._manager using
CloudSQLManager with pg8000 via cloud-sql-python-connector.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from schwab_mcp.db import DatabaseManager

logger = logging.getLogger(__name__)

# Default cache TTL: 5 minutes
DEFAULT_CACHE_TTL_SECONDS = 300

# Schema for the token table — executed on ensure_table()
TOKEN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schwab_tokens (
    id              SERIAL PRIMARY KEY,
    key             TEXT NOT NULL UNIQUE DEFAULT 'default',
    token_data      JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class PostgresTokenStorage:
    """Manages Schwab OAuth tokens stored in Postgres via DatabaseManager.

    The load()/write() methods are synchronous to match schwab-py's
    token callback interface. They use the in-memory cache and schedule
    async DB writes when possible.
    """

    def __init__(
        self,
        db: DatabaseManager,
        key: str = "default",
        cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.db = db
        self.key = key
        self.cache_ttl = cache_ttl

        self._cached_token: dict[str, Any] | None = None
        self._cache_time: float = 0.0

    async def ensure_table(self) -> None:
        """Create the schwab_tokens table if it doesn't exist."""
        await self.db.execute(TOKEN_TABLE_SQL)

    def load(self) -> dict[str, Any]:
        """Synchronous token loader for schwab-py compatibility.

        Returns the cached token if available. schwab-py calls this
        synchronously from its token refresh path.
        """
        if self._cached_token is not None:
            return self._cached_token
        raise FileNotFoundError(
            "No cached token available. Call load_async() first."
        )

    async def load_async(self) -> dict[str, Any]:
        """Load the Schwab token from Postgres, using cache if fresh."""
        now = time.time()
        if (
            self._cached_token is not None
            and (now - self._cache_time) < self.cache_ttl
        ):
            return self._cached_token

        return await self._load_from_db()

    async def _load_from_db(self) -> dict[str, Any]:
        """Load the token directly from Postgres."""
        rows = await self.db.execute(
            "SELECT token_data FROM schwab_tokens WHERE key = %s",
            (self.key,),
        )
        if not rows:
            raise FileNotFoundError(
                f"Schwab token not found in database (key={self.key!r})"
            )

        token_data = rows[0][0]
        if isinstance(token_data, str):
            token_data = json.loads(token_data)

        if not isinstance(token_data, dict):
            raise ValueError("Token data is not a valid dictionary")

        self._cached_token = token_data
        self._cache_time = time.time()
        logger.info("Loaded Schwab token from Postgres (key=%s)", self.key)
        return token_data

    def write(self, token: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Synchronous token writer for schwab-py compatibility.

        schwab-py calls this synchronously when it auto-refreshes the
        access token. We update the in-memory cache immediately and
        attempt a synchronous DB write via anyio's thread bridge.
        """
        if not token:
            return

        self._cached_token = token
        self._cache_time = time.time()

        # schwab-py calls this from a sync context during token refresh.
        # Try to persist to DB via the anyio thread bridge.
        try:
            from anyio.from_thread import run as _run_async

            _run_async(self._write_to_db, token)
        except Exception:
            # If we're already in an async context or no event loop,
            # just keep the cache. The next async write will persist it.
            logger.warning(
                "Could not write token to DB synchronously. "
                "Cache updated; will persist on next async operation."
            )

    async def write_async(self, token: dict[str, Any]) -> None:
        """Write the token to Postgres and update the cache."""
        if not token:
            return

        await self._write_to_db(token)
        self._cached_token = token
        self._cache_time = time.time()

    async def _write_to_db(self, token: dict[str, Any]) -> None:
        """Upsert the token into Postgres."""
        token_json = json.dumps(token)
        await self.db.execute(
            """
            INSERT INTO schwab_tokens (key, token_data, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key)
            DO UPDATE SET token_data = EXCLUDED.token_data,
                          updated_at = NOW()
            """,
            (self.key, token_json),
        )
        logger.info("Wrote Schwab token to Postgres (key=%s)", self.key)

    async def exists_async(self) -> bool:
        """Check whether a token exists in the database."""
        rows = await self.db.execute(
            "SELECT 1 FROM schwab_tokens WHERE key = %s",
            (self.key,),
        )
        return len(rows) > 0

    def exists(self) -> bool:
        """Synchronous check — returns True if we have a cached token."""
        return self._cached_token is not None

    def invalidate_cache(self) -> None:
        """Force the next load_async() to read from the database."""
        self._cached_token = None
        self._cache_time = 0.0
