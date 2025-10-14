from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
    """Call a method on the Schwab client and return the response text."""

    response = await func(*args, **kwargs)
    response.raise_for_status()
    return response.text


__all__ = ["call"]
