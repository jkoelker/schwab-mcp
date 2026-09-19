"""In-memory store for pending order previews awaiting write confirmation."""

from __future__ import annotations

import copy
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

_DEFAULT_TTL: float = 600.0  # 10 minutes


class PreviewOperation(str, Enum):
    """Identify the write operation authorized by a cached preview."""

    PLACE_ORDER = "PLACE_ORDER"
    REPLACE_ORDER = "REPLACE_ORDER"


@dataclass(frozen=True, slots=True)
class PreviewEntry:
    """A cached order preview awaiting its authorized write operation."""

    order_spec: dict[str, Any]
    account_hash: str
    tool_name: str
    summary: str
    created_at: float
    operation: PreviewOperation
    target_order_id: str | None


class PreviewStore:
    """In-memory store for pending order previews with TTL expiry."""

    _entries: dict[str, PreviewEntry]
    _ttl: float

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._entries = {}
        self._ttl = ttl

    @staticmethod
    def _coerce_operation(operation: PreviewOperation | str) -> PreviewOperation:
        """Convert an operation value to the store's discriminator enum."""
        try:
            return PreviewOperation(operation)
        except ValueError as exc:
            raise ValueError(f"Unknown preview operation: {operation!r}.") from exc

    def _prune(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired_preview_ids = [
            preview_id for preview_id, entry in self._entries.items() if entry.created_at + self._ttl < now
        ]
        for preview_id in expired_preview_ids:
            del self._entries[preview_id]

    def put(
        self,
        account_hash: str,
        order_spec: dict[str, Any],
        tool_name: str,
        summary: str,
        *,
        operation: PreviewOperation | str,
        target_order_id: str | None = None,
    ) -> str:
        """Store a preview entry and return its 16-char hex id.

        The order_spec is deep-copied before storage so later mutation of the
        caller's dict cannot change what gets placed later.
        """
        normalized_operation = self._coerce_operation(operation)
        normalized_target_order_id = target_order_id.strip() if target_order_id is not None else None
        if normalized_operation is PreviewOperation.REPLACE_ORDER and not normalized_target_order_id:
            raise ValueError("Replacement previews require a target order id.")
        if normalized_operation is PreviewOperation.PLACE_ORDER and normalized_target_order_id is not None:
            raise ValueError("Placement previews cannot bind a replacement target.")

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
            operation=normalized_operation,
            target_order_id=normalized_target_order_id,
        )
        return preview_id

    def pop(
        self,
        preview_id: str,
        account_hash: str,
        *,
        operation: PreviewOperation | str,
    ) -> PreviewEntry:
        """Retrieve and remove a preview entry, validating id and account_hash.

        Raises:
            ValueError: If the id is unknown or the entry has expired.
            ValueError: If the account_hash does not match the stored entry.
        """
        normalized_operation = self._coerce_operation(operation)
        entry = self._entries.get(preview_id)
        if entry is None or entry.created_at + self._ttl < time.monotonic():
            self._entries.pop(preview_id, None)
            raise ValueError(f"Preview '{preview_id}' not found or expired.")
        if entry.account_hash != account_hash:
            raise ValueError("Account hash mismatch: preview was created for a different account.")
        if entry.operation is not normalized_operation:
            raise ValueError(f"Preview operation mismatch: expected {normalized_operation.value}.")
        del self._entries[preview_id]
        return entry


__all__ = ["PreviewEntry", "PreviewOperation", "PreviewStore"]
