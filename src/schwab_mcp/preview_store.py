from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, TypeAlias

# Duplicated from schwab_mcp.tools.utils.JSONType rather than imported: this
# module is used by schwab_mcp.context, which loads before the schwab_mcp.tools
# package finishes initializing, so importing from schwab_mcp.tools here would
# reintroduce a circular import.
JSONType: TypeAlias = str | int | float | bool | None | dict[str, Any] | list[Any]

_DEFAULT_TTL = timedelta(minutes=10)
_DEFAULT_MAX_ENTRIES = 100


@dataclass(slots=True, frozen=True)
class PreviewEntry:
    """A stored result of previewing an order, keyed by ``preview_id``."""

    preview_id: str
    account_hash: str
    order_spec: dict[str, Any]
    preview_response: JSONType
    summary: str
    created_at: datetime

    def is_expired(self, ttl: timedelta) -> bool:
        return datetime.now(timezone.utc) - self.created_at > ttl


@dataclass(slots=True)
class PreviewStore:
    """In-memory, process-lifetime store linking a generated preview_id to the
    exact order spec that was previewed.

    Schwab's previewOrder endpoint is stateless/advisory only -- it has no
    server-side concept of submitting a previously previewed order by ID. This
    store implements that linkage locally so a later ``submit_previewed_order``
    call resubmits the exact stored order spec that was previewed, rather than
    trusting the caller to reconstruct it correctly.

    Entries are not persisted and do not survive a server restart, consistent
    with the in-memory lifetime of ``ApprovalManager`` state. Capped at
    ``max_entries``, evicting the oldest entry first, to bound memory use if a
    caller creates many previews without ever submitting or expiring them.
    """

    ttl: timedelta = _DEFAULT_TTL
    max_entries: int = _DEFAULT_MAX_ENTRIES
    _entries: dict[str, PreviewEntry] = field(default_factory=dict)

    def put(
        self,
        account_hash: str,
        order_spec: dict[str, Any],
        preview_response: JSONType,
        summary: str,
    ) -> PreviewEntry:
        self._evict_expired()
        self._evict_oldest_if_full()
        entry = PreviewEntry(
            preview_id=str(uuid.uuid4()),
            account_hash=account_hash,
            # Deep-copied so a caller mutating their own order_spec dict after
            # this call can't silently change what gets submitted later.
            order_spec=copy.deepcopy(order_spec),
            preview_response=preview_response,
            summary=summary,
            created_at=datetime.now(timezone.utc),
        )
        self._entries[entry.preview_id] = entry
        return entry

    def peek(self, preview_id: str) -> PreviewEntry:
        """Look up an entry without removing it. Raises ``ValueError`` if the
        preview is unknown or has expired."""
        entry = self._entries.get(preview_id)
        if entry is None:
            raise ValueError(f"Preview {preview_id!r} not found")
        if entry.is_expired(self.ttl):
            del self._entries[preview_id]
            raise ValueError(f"Preview {preview_id!r} expired")
        return entry

    def pop(self, preview_id: str) -> PreviewEntry:
        """Look up and remove an entry (one-time use). Raises ``ValueError``
        under the same conditions as :meth:`peek`."""
        entry = self.peek(preview_id)
        del self._entries[preview_id]
        return entry

    def _evict_expired(self) -> None:
        expired = [
            pid for pid, entry in self._entries.items() if entry.is_expired(self.ttl)
        ]
        for pid in expired:
            del self._entries[pid]

    def _evict_oldest_if_full(self) -> None:
        # dicts preserve insertion order and entries are never reordered, so
        # the first key is always the oldest surviving entry.
        while len(self._entries) >= self.max_entries:
            oldest_id = next(iter(self._entries))
            del self._entries[oldest_id]


__all__ = ["PreviewEntry", "PreviewStore"]
