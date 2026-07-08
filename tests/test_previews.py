from __future__ import annotations

import pytest

import schwab_mcp.previews as previews_module
from schwab_mcp.previews import PreviewStore

SPEC: dict = {"orderType": "LIMIT", "price": "150.00"}
ACCOUNT = "abc123"
TOOL = "preview_equity_order"
SUMMARY = "BUY 100 AAPL LIMIT $150.00"


def test_put_pop_round_trip():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)
    entry = store.pop(preview_id, ACCOUNT)
    assert entry.order_spec == SPEC
    assert entry.tool_name == TOOL
    assert entry.summary == SUMMARY
    assert entry.account_hash == ACCOUNT


def test_pop_unknown_id_raises():
    store = PreviewStore()
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop("f" * 16, ACCOUNT)


def test_put_deep_copies_order_spec():
    spec = {"orderType": "LIMIT", "legs": [{"symbol": "AAPL"}]}
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, spec, TOOL, SUMMARY)

    # Mutate the caller's dict after put() — the cached copy must be unaffected.
    spec["orderType"] = "MARKET"
    spec["legs"][0]["symbol"] = "MSFT"

    entry = store.pop(preview_id, ACCOUNT)
    assert entry.order_spec == {"orderType": "LIMIT", "legs": [{"symbol": "AAPL"}]}


def test_pop_consumes_entry():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)
    store.pop(preview_id, ACCOUNT)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT)


def test_pop_wrong_account_raises_and_does_not_remove():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)

    with pytest.raises(ValueError, match="Account hash mismatch"):
        store.pop(preview_id, "wrong_account")

    # Entry must still be present — correct account should still work
    entry = store.pop(preview_id, ACCOUNT)
    assert entry.account_hash == ACCOUNT


def test_pop_expired_raises(monkeypatch):
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)

    # Advance past TTL
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT)


def test_pop_removes_expired_entry_immediately(monkeypatch):
    """pop() on an expired entry should evict it right away, not just raise —
    it shouldn't wait for a future put() to prune it."""
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)

    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT)

    assert preview_id not in store._entries


def test_lazy_prune_on_put(monkeypatch):
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)

    id1 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)
    id2 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)
    id3 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)

    # Advance past TTL, then put a 4th entry (triggers lazy prune)
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    id4 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)

    # The first 3 should be gone
    for stale_id in (id1, id2, id3):
        with pytest.raises(ValueError, match="not found or expired"):
            store.pop(stale_id, ACCOUNT)

    # The 4th should still be present
    entry = store.pop(id4, ACCOUNT)
    assert entry.summary == SUMMARY


def test_id_format():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY)
    assert len(preview_id) == 16
    assert preview_id == preview_id.lower()
    assert all(c in "0123456789abcdef" for c in preview_id)
