"""Approval channel hygiene: pending cap, unverified client label, masked accounts."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from conftest import make_ctx, run

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.approvals.discord import DiscordApprovalManager, DiscordApprovalSettings
from schwab_mcp.previews import PreviewOperation
from schwab_mcp.tools import _registration, account, orders


def _request(index: int) -> ApprovalRequest:
    return ApprovalRequest(
        id=f"approval-{index}", tool_name="cancel_order", request_id="req", client_id=None, arguments={}
    )


class GatedApprovals(ApprovalManager):
    """Holds every request until released, counting what reached the backend."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.release = asyncio.Event()

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        self.seen.append(request.id)
        await self.release.wait()
        return ApprovalDecision.APPROVED


def test_fourth_concurrent_approval_is_refused_before_backend() -> None:
    ctx = make_ctx(object())
    manager = GatedApprovals()
    ctx.schwab.approval_manager = manager

    async def scenario() -> list[Any]:
        pending = [asyncio.create_task(_registration.run_approval(ctx, _request(i))) for i in range(3)]
        await asyncio.sleep(0)
        with pytest.raises(PermissionError, match="3 approvals are already pending"):
            await asyncio.wait_for(_registration.run_approval(ctx, _request(3)), timeout=1)
        manager.release.set()
        return await asyncio.gather(*pending)

    decisions = asyncio.run(asyncio.wait_for(scenario(), timeout=5))

    assert decisions == [ApprovalDecision.APPROVED] * 3
    assert manager.seen == ["approval-0", "approval-1", "approval-2"]


def test_pending_slots_free_up_after_decisions() -> None:
    ctx = make_ctx(object())
    manager = GatedApprovals()
    manager.release.set()
    ctx.schwab.approval_manager = manager

    for index in range(5):
        assert run(_registration.run_approval(ctx, _request(index))) is ApprovalDecision.APPROVED

    assert len(manager.seen) == 5


def test_pending_slot_freed_when_backend_raises() -> None:
    ctx = make_ctx(object())

    class Broken(ApprovalManager):
        async def require(self, request: ApprovalRequest) -> ApprovalDecision:
            raise RuntimeError("backend down")

    ctx.schwab.approval_manager = Broken()
    for _ in range(4):
        with pytest.raises(RuntimeError, match="backend down"):
            run(_registration.run_approval(ctx, _request(0)))


@pytest.mark.parametrize("builder", ["_build_pending_embed", "_finalize"])
def test_discord_labels_client_id_unverified(builder: str) -> None:
    from unittest.mock import patch

    with patch("schwab_mcp.approvals.discord._ApprovalClient"):
        manager = DiscordApprovalManager(DiscordApprovalSettings(token="t", channel_id=1, approver_ids=frozenset({2})))
    request = ApprovalRequest(id="a", tool_name="cancel_order", request_id="r", client_id="spoofable", arguments={})

    if builder == "_build_pending_embed":
        embed = manager._build_pending_embed(request)
    else:
        message = MagicMock()

        async def edit(**kwargs: Any) -> None:
            message.embed = kwargs["embed"]

        message.edit = edit
        run(manager._finalize_message(message, request, ApprovalDecision.DENIED, actor=None, reason=None))
        embed = message.embed

    names = [field.name for field in embed.fields]
    assert "Client ID (unverified)" in names
    assert "Client ID" not in names


_ACCOUNTS = [
    {"securitiesAccount": {"accountNumber": "12345678", "type": "MARGIN"}},
    {"securitiesAccount": {"accountNumber": "87654321", "type": "CASH"}},
]


@pytest.fixture
def account_ctx(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def fake_call(func: Any, *args: Any, **kwargs: Any) -> Any:
        name = getattr(func, "__name__", "")
        if name == "get_account_numbers":
            return [
                {"accountNumber": "12345678", "hashValue": "HASHA"},
                {"accountNumber": "87654321", "hashValue": "HASHB"},
            ]
        if name == "get_user_preferences":
            return {"accounts": [{"accountNumber": "12345678", "nickName": "Main", "primaryAccount": True}]}
        if name == "get_account":
            return {"securitiesAccount": {"accountNumber": "87654321", "type": "CASH"}}
        return [dict(item, securitiesAccount=dict(item["securitiesAccount"])) for item in _ACCOUNTS]

    monkeypatch.setattr(account, "call", fake_call)

    class Client:
        class Account:
            class Fields:
                POSITIONS = "positions"

        async def get_account_numbers(self) -> Any: ...
        async def get_user_preferences(self) -> Any: ...
        async def get_accounts(self, **kwargs: Any) -> Any: ...
        async def get_account(self, *args: Any, **kwargs: Any) -> Any: ...

    return make_ctx(Client())


def test_compact_accounts_mask_number_after_enrichment(account_ctx: Any) -> None:
    result = run(account.get_accounts(account_ctx))

    secs = [item["securitiesAccount"] for item in result]
    assert [sec["accountNumber"] for sec in secs] == ["...5678", "...4321"]
    assert [sec["accountHash"] for sec in secs] == ["HASHA", "HASHB"]
    assert secs[0]["nickname"] == "Main"
    assert secs[0]["isDefault"] is True


def test_compact_single_account_is_masked(account_ctx: Any) -> None:
    result = run(account.get_account(account_ctx, "HASHB"))

    assert result["securitiesAccount"]["accountNumber"] == "...4321"
    assert result["securitiesAccount"]["accountHash"] == "HASHB"


def test_verbose_accounts_keep_full_number(account_ctx: Any) -> None:
    result = run(account.get_accounts(account_ctx, verbose=True))

    assert [item["securitiesAccount"]["accountNumber"] for item in result] == ["12345678", "87654321"]


# A cap refusal must not consume the single-use preview.


@pytest.mark.parametrize(
    ("tool", "operation", "target"),
    [
        ("place_previewed_order", "PLACE_ORDER", None),
        ("replace_previewed_order", "REPLACE_ORDER", "order-9"),
    ],
)
def test_cap_refusal_keeps_preview_usable(tool: str, operation: str, target: str | None) -> None:
    ctx = make_ctx(object())
    ctx.schwab.approval_manager = GatedApprovals()
    account_hash = "A" * 64
    preview_id = ctx.previews.put(
        account_hash,
        {"orderStrategyType": "SINGLE"},
        "preview_equity_order",
        "SINGLE BUY 1 AAPL EQUITY MARKET",
        operation=PreviewOperation[operation],
        target_order_id=target,
    )
    ctx.schwab.pending_approvals = _registration.MAX_PENDING_APPROVALS

    with pytest.raises(PermissionError, match="already pending"):
        run(getattr(orders, tool)(ctx, account_hash, preview_id))

    entry = ctx.previews.pop(preview_id, account_hash, operation=PreviewOperation[operation])
    assert entry.summary == "SINGLE BUY 1 AAPL EQUITY MARKET"
