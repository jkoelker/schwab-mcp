"""Approval workflow backends for write-tool gating."""

from __future__ import annotations

from schwab_mcp.approvals.base import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    NoOpApprovalManager,
)
from schwab_mcp.approvals.discord import (
    DiscordApprovalManager,
    DiscordApprovalSettings,
)
from schwab_mcp.approvals.signal import (
    SignalApprovalManager,
    SignalApprovalSettings,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalManager",
    "ApprovalRequest",
    "NoOpApprovalManager",
    "DiscordApprovalManager",
    "DiscordApprovalSettings",
    "SignalApprovalManager",
    "SignalApprovalSettings",
]
