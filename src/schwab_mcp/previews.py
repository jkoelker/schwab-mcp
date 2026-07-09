"""In-memory store for pending order previews awaiting placement confirmation."""

from __future__ import annotations

import copy
import secrets
import time
from dataclasses import dataclass
from typing import Any

_DEFAULT_TTL: float = 600.0  # 10 minutes


@dataclass(slots=True)
class PreviewEntry:
    """A cached order preview awaiting placement."""

    order_spec: dict[str, Any]
    account_hash: str
    tool_name: str
    summary: str
    created_at: float


class PreviewStore:
    """In-memory store for pending order previews with TTL expiry."""

    _entries: dict[str, PreviewEntry]
    _ttl: float

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._entries = {}
        self._ttl = ttl

    def _prune(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired = [k for k, v in self._entries.items() if v.created_at + self._ttl < now]
        for k in expired:
            del self._entries[k]

    def put(
        self,
        account_hash: str,
        order_spec: dict[str, Any],
        tool_name: str,
        summary: str,
    ) -> str:
        """Store a preview entry and return its 16-char hex id.

        The order_spec is deep-copied before storage so later mutation of the
        caller's dict cannot change what gets placed later.
        """
        self._prune()
        while True:
            preview_id = secrets.token_hex(8)
            if preview_id not in self._entries:
                break
        self._entries[preview_id] = PreviewEntry(
            order_spec=copy.deepcopy(order_spec),
            account_hash=account_hash,
            tool_name=tool_name,
            summary=summary,
            created_at=time.monotonic(),
        )
        return preview_id

    def pop(self, preview_id: str, account_hash: str) -> PreviewEntry:
        """Retrieve and remove a preview entry, validating id and account_hash.

        Raises:
            ValueError: If the id is unknown or the entry has expired.
            ValueError: If the account_hash does not match the stored entry.
        """
        entry = self._entries.get(preview_id)
        if entry is None or entry.created_at + self._ttl < time.monotonic():
            self._entries.pop(preview_id, None)
            raise ValueError(f"Preview '{preview_id}' not found or expired.")
        if entry.account_hash != account_hash:
            raise ValueError("Account hash mismatch: preview was created for a different account.")
        del self._entries[preview_id]
        return entry


__all__ = ["PreviewEntry", "PreviewStore"]
