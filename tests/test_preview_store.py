import datetime
from datetime import timedelta

import pytest

from schwab_mcp.preview_store import PreviewEntry, PreviewStore


def test_put_returns_entry_with_generated_id_and_stored_fields():
    store = PreviewStore()

    entry = store.put("hash1", {"orderType": "MARKET"}, {"ok": True}, "BUY 1 AAPL")

    assert entry.preview_id
    assert entry.account_hash == "hash1"
    assert entry.order_spec == {"orderType": "MARKET"}
    assert entry.preview_response == {"ok": True}
    assert entry.summary == "BUY 1 AAPL"


def test_peek_returns_entry_without_removing_it():
    store = PreviewStore()
    entry = store.put("hash1", {}, {}, "summary")

    peeked = store.peek(entry.preview_id)

    assert peeked == entry
    # Still retrievable a second time.
    assert store.peek(entry.preview_id) == entry


def test_pop_returns_entry_and_removes_it():
    store = PreviewStore()
    entry = store.put("hash1", {}, {}, "summary")

    popped = store.pop(entry.preview_id)

    assert popped == entry
    with pytest.raises(ValueError, match="not found"):
        store.peek(entry.preview_id)


def test_peek_unknown_id_raises_value_error():
    store = PreviewStore()

    with pytest.raises(ValueError, match="not found"):
        store.peek("does-not-exist")


def test_pop_unknown_id_raises_value_error():
    store = PreviewStore()

    with pytest.raises(ValueError, match="not found"):
        store.pop("does-not-exist")


def test_peek_expired_entry_raises_and_evicts():
    store = PreviewStore(ttl=timedelta(seconds=0))
    entry = store.put("hash1", {}, {}, "summary")

    with pytest.raises(ValueError, match="expired"):
        store.peek(entry.preview_id)

    # Evicted on expiry detection -- second lookup reports "not found".
    with pytest.raises(ValueError, match="not found"):
        store.peek(entry.preview_id)


def test_pop_expired_entry_raises_value_error():
    store = PreviewStore(ttl=timedelta(seconds=0))
    entry = store.put("hash1", {}, {}, "summary")

    with pytest.raises(ValueError, match="expired"):
        store.pop(entry.preview_id)


def test_put_evicts_other_expired_entries():
    store = PreviewStore(ttl=timedelta(seconds=0))
    stale = store.put("hash1", {}, {}, "stale")

    store.put("hash2", {}, {}, "fresh")

    with pytest.raises(ValueError, match="not found"):
        store.peek(stale.preview_id)


def test_put_evicts_oldest_entry_when_over_max_entries():
    store = PreviewStore(max_entries=2)

    first = store.put("hash1", {}, {}, "first")
    second = store.put("hash1", {}, {}, "second")
    third = store.put("hash1", {}, {}, "third")

    # Oldest entry was evicted to make room; the rest are untouched.
    with pytest.raises(ValueError, match="not found"):
        store.peek(first.preview_id)
    assert store.peek(second.preview_id) == second
    assert store.peek(third.preview_id) == third


def test_put_does_not_evict_when_expired_entries_free_up_room():
    store = PreviewStore(ttl=timedelta(seconds=0), max_entries=2)
    store.put("hash1", {}, {}, "stale-1")
    store.put("hash1", {}, {}, "stale-2")

    # Both prior entries are already expired, so put() should evict them via
    # _evict_expired() rather than falling through to oldest-entry eviction.
    store.put("hash1", {}, {}, "fresh")

    assert len(store._entries) == 1  # noqa: SLF001 - test-only introspection


def test_is_expired_uses_ttl_boundary():
    now = datetime.datetime.now(datetime.timezone.utc)
    entry = PreviewEntry(
        preview_id="id",
        account_hash="hash",
        order_spec={},
        preview_response=None,
        summary="s",
        created_at=now - timedelta(minutes=5),
    )

    assert entry.is_expired(timedelta(minutes=1)) is True
    assert entry.is_expired(timedelta(minutes=10)) is False
