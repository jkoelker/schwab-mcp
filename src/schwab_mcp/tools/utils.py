from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias


JSONPrimitive = str | int | float | bool | None
JSONType: TypeAlias = JSONPrimitive | dict[str, "JSONType"] | list["JSONType"]


async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> JSONType:
    """Call a Schwab client endpoint and return its JSON payload."""

    response = await func(*args, **kwargs)
    response.raise_for_status()

    if getattr(response, "status_code", None) == 204:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Expected JSON response from Schwab endpoint") from exc


__all__ = ["call", "JSONType"]
