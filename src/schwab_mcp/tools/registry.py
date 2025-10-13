from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar, overload
P = ParamSpec("P")
R = TypeVar("R")

RegisteredTool = Callable[P, Awaitable[R]]

_REGISTERED_TOOLS: list[Callable[..., Awaitable[Any]]] = []


@overload
def register(
    func: RegisteredTool,
    *,
    write: bool = False,
) -> RegisteredTool:
    ...


@overload
def register(
    func: None = None,
    *,
    write: bool = False,
) -> Callable[[RegisteredTool], RegisteredTool]:
    ...


def register(
    func: RegisteredTool | None = None,
    *,
    write: bool = False,
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
    """

    def _decorator(fn: RegisteredTool) -> RegisteredTool:
        setattr(fn, "_write", write)
        _REGISTERED_TOOLS.append(fn)  # type: ignore[arg-type]
        return fn

    if func is not None:
        return _decorator(func)

    return _decorator


def iter_registered_tools() -> list[Callable[..., Awaitable[Any]]]:
    """Return a copy of the registered tool callables."""
    return list(_REGISTERED_TOOLS)


__all__ = ["register", "iter_registered_tools", "RegisteredTool"]
