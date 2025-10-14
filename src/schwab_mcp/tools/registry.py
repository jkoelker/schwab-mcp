from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar, overload

from mcp.types import ToolAnnotations

P = ParamSpec("P")
R = TypeVar("R")

RegisteredTool = Callable[P, Awaitable[R]]

_REGISTERED_TOOLS: list[Callable[..., Awaitable[Any]]] = []


@overload
def register(
    func: RegisteredTool,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
) -> RegisteredTool: ...


@overload
def register(
    func: None = None,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
) -> Callable[[RegisteredTool], RegisteredTool]: ...


def register(
    func: RegisteredTool | None = None,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
) -> RegisteredTool | Callable[[RegisteredTool], RegisteredTool]:
    """Decorator used by tool modules to mark async callables for registration.

    Parameters
    ----------
    func:
        The async function being registered. When omitted, the decorator can be
        used with keyword arguments (e.g., ``@register(write=True)``).
    write:
        Flag indicating whether the tool performs a write/side-effecting
        operation that should only be exposed when the server is started with
        explicit write access enabled.
    annotations:
        Optional MCP tool annotations to attach when the tool is registered.
        Defaults to describing the tool as read-only unless ``write`` is True.
    """

    def _decorator(fn: RegisteredTool) -> RegisteredTool:
        setattr(fn, "_write", write)
        default_annotations = ToolAnnotations(
            readOnlyHint=not write,
            destructiveHint=True if write else None,
        )
        if annotations is not None:
            update: dict[str, Any] = {}
            if annotations.readOnlyHint is None:
                update["readOnlyHint"] = not write
            if write and annotations.destructiveHint is None:
                update["destructiveHint"] = True
            tool_annotations = annotations.model_copy(update=update)
        else:
            tool_annotations = default_annotations

        setattr(fn, "_tool_annotations", tool_annotations)
        _REGISTERED_TOOLS.append(fn)  # type: ignore[arg-type]
        return fn

    if func is not None:
        return _decorator(func)

    return _decorator


def iter_registered_tools() -> list[Callable[..., Awaitable[Any]]]:
    """Return a copy of the registered tool callables."""
    return list(_REGISTERED_TOOLS)


__all__ = ["register", "iter_registered_tools", "RegisteredTool"]
