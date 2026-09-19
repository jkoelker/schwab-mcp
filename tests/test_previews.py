from __future__ import annotations

import pytest

import schwab_mcp.previews as previews_module
from schwab_mcp.previews import PreviewOperation, PreviewStore

SPEC: dict = {"orderType": "LIMIT", "price": "150.00"}
ACCOUNT = "abc123"
TOOL = "preview_equity_order"
SUMMARY = "BUY 100 AAPL LIMIT $150.00"


def test_put_pop_round_trip():
    """Placement previews round-trip with an explicit operation discriminator."""
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)
    entry = store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    assert entry.order_spec == SPEC
    assert entry.tool_name == TOOL
    assert entry.summary == SUMMARY
    assert entry.account_hash == ACCOUNT
    assert entry.operation is PreviewOperation.PLACE_ORDER
    assert entry.target_order_id is None


def test_replacement_preview_binds_target_and_operation():
    """Replacement previews retain their target order and operation binding."""
    store = PreviewStore()
    preview_id = store.put(
        ACCOUNT,
        SPEC,
        "preview_replacement_order",
        SUMMARY,
        operation=PreviewOperation.REPLACE_ORDER,
        target_order_id="order-7",
    )

    entry = store.pop(preview_id, ACCOUNT, operation=PreviewOperation.REPLACE_ORDER)

    assert entry.operation is PreviewOperation.REPLACE_ORDER
    assert entry.target_order_id == "order-7"


def test_operation_mismatch_does_not_consume_preview():
    """An executor using the wrong operation cannot consume a preview."""
    store = PreviewStore()
    preview_id = store.put(
        ACCOUNT,
        SPEC,
        "preview_replacement_order",
        SUMMARY,
        operation=PreviewOperation.REPLACE_ORDER,
        target_order_id="order-7",
    )

    with pytest.raises(ValueError, match="operation mismatch"):
        store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)

    assert store.pop(preview_id, ACCOUNT, operation=PreviewOperation.REPLACE_ORDER).target_order_id == "order-7"


def test_replacement_target_id_is_stripped():
    """The preview store normalizes replacement target IDs before storage."""
    store = PreviewStore()
    preview_id = store.put(
        ACCOUNT,
        SPEC,
        "preview_replacement_order",
        SUMMARY,
        operation=PreviewOperation.REPLACE_ORDER,
        target_order_id="  order-7  ",
    )

    entry = store.pop(preview_id, ACCOUNT, operation=PreviewOperation.REPLACE_ORDER)

    assert entry.target_order_id == "order-7"


def test_blank_replacement_target_id_is_rejected():
    """The preview store rejects replacement target IDs without content."""
    store = PreviewStore()

    with pytest.raises(ValueError, match="target order id"):
        store.put(
            ACCOUNT,
            SPEC,
            "preview_replacement_order",
            SUMMARY,
            operation=PreviewOperation.REPLACE_ORDER,
            target_order_id="   ",
        )


def test_pop_unknown_id_raises():
    store = PreviewStore()
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop("f" * 16, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)


def test_put_deep_copies_order_spec():
    spec = {"orderType": "LIMIT", "legs": [{"symbol": "AAPL"}]}
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, spec, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    # Mutate the caller's dict after put() — the cached copy must be unaffected.
    spec["orderType"] = "MARKET"
    spec["legs"][0]["symbol"] = "MSFT"

    entry = store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    assert entry.order_spec == {"orderType": "LIMIT", "legs": [{"symbol": "AAPL"}]}


def test_pop_consumes_entry():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)
    store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)


def test_pop_wrong_account_raises_and_does_not_remove():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    with pytest.raises(ValueError, match="Account hash mismatch"):
        store.pop(preview_id, "wrong_account", operation=PreviewOperation.PLACE_ORDER)

    # Entry must still be present — correct account should still work
    entry = store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    assert entry.account_hash == ACCOUNT


def test_pop_expired_raises(monkeypatch):
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    # Advance past TTL
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)


def test_pop_removes_expired_entry_immediately(monkeypatch):
    """pop() on an expired entry should evict it right away, not just raise —
    it shouldn't wait for a future put() to prune it."""
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    with pytest.raises(ValueError, match="not found or expired"):
        store.pop(preview_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)

    assert preview_id not in store._entries


def test_lazy_prune_on_put(monkeypatch):
    store = PreviewStore(ttl=10.0)
    t = 1000.0
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t)

    id1 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)
    id2 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)
    id3 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    # Advance past TTL, then put a 4th entry (triggers lazy prune)
    monkeypatch.setattr(previews_module.time, "monotonic", lambda: t + 11.0)
    id4 = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)

    # The first 3 should be gone
    for stale_id in (id1, id2, id3):
        with pytest.raises(ValueError, match="not found or expired"):
            store.pop(stale_id, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)

    # The 4th should still be present
    entry = store.pop(id4, ACCOUNT, operation=PreviewOperation.PLACE_ORDER)
    assert entry.summary == SUMMARY


def test_id_format():
    store = PreviewStore()
    preview_id = store.put(ACCOUNT, SPEC, TOOL, SUMMARY, operation=PreviewOperation.PLACE_ORDER)
    assert len(preview_id) == 16
    assert preview_id == preview_id.lower()
    assert all(c in "0123456789abcdef" for c in preview_id)
