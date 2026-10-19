"""Base classes and data types for the approval workflow."""

from __future__ import annotations

import abc
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

logger = logging.getLogger(__name__)


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


def format_arguments(arguments: Mapping[str, str]) -> str:
    """Render approval arguments as a fenced text block.

    Backticks in values are attacker-controlled (LLM-supplied) and would close
    a markdown code fence early, re-enabling live formatting. Substitute a
    visually similar non-metacharacter so the fence cannot be broken. Shared
    so every approval backend renders arguments the same way.
    """
    if not arguments:
        return "```\n<none>\n```"

    lines = [f"{key} = {value}" for key, value in arguments.items()]
    body = "\n".join(lines).replace("`", "ˋ")
    return f"```\n{body}\n```"


def parse_account_names(values: Sequence[str] | None) -> Mapping[str, str]:
    """Parse ``last4=Name`` entries (from CLI flags or comma-split env) into
    an immutable mapping. Repeated keys: last value wins. Whitespace and
    empty entries are ignored. Missing separators or empty keys/names are
    skipped with a warning. Other keys and names are stored unchanged.
    """
    if not values:
        return MappingProxyType({})
    result: dict[str, str] = {}
    for raw in values:
        if not raw:
            continue
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" not in chunk:
                logger.warning(
                    "Ignoring malformed account-name entry %r (expected 'last4=Name')",
                    chunk,
                )
                continue
            last4, _, name = chunk.partition("=")
            last4 = last4.strip()
            name = name.strip()
            if not last4 or not name:
                logger.warning("Ignoring empty account-name entry %r", chunk)
                continue
            result[last4] = name
    return MappingProxyType(result)


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
    "format_arguments",
    "parse_account_names",
]
