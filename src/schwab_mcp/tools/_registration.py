from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ToolFn = Callable[..., Awaitable[Any]]


def register_tool(
    server: FastMCP,
    func: ToolFn,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
) -> None:
    """Register a Schwab tool using FastMCP's decorator plumbing."""

    tool_annotations = annotations
    if tool_annotations is None:
        if write:
            tool_annotations = ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
            )
        else:
            tool_annotations = ToolAnnotations(
                readOnlyHint=True,
            )
    else:
        update: dict[str, Any] = {}
        if tool_annotations.readOnlyHint is None:
            update["readOnlyHint"] = not write
        if write and tool_annotations.destructiveHint is None:
            update["destructiveHint"] = True
        if update:
            tool_annotations = tool_annotations.model_copy(update=update)

    server.tool(
        name=func.__name__,
        description=func.__doc__,
        annotations=tool_annotations,
    )(func)


__all__ = ["register_tool"]
