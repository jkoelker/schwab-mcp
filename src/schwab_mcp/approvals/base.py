"""Base classes and data types for the approval workflow."""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class ApprovalDecision(str, Enum):
    """Decision returned by an approval workflow."""

    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(slots=True, frozen=True)
class ApprovalRequest:
    """Details about a write tool invocation requiring approval."""

    id: str
    tool_name: str
    request_id: str
    client_id: str | None
    arguments: Mapping[str, str]


class ApprovalManager(abc.ABC):
    """Interface for asynchronous approval backends."""

    async def start(self) -> None:  # noqa: B027
        """Perform any startup/connection work."""

    async def stop(self) -> None:  # noqa: B027
        """Clean up resources."""

    @abc.abstractmethod
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        """Require approval for the provided request."""


class NoOpApprovalManager(ApprovalManager):
    """Approval manager that always approves requests."""

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        """Always approve the request without any external check."""
        return ApprovalDecision.APPROVED


__all__ = [
    "ApprovalDecision",
    "ApprovalManager",
    "ApprovalRequest",
    "NoOpApprovalManager",
]
