from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias


JSONPrimitive = str | int | float | bool | None
JSONType: TypeAlias = JSONPrimitive | dict[str, Any] | list[Any]


class SchwabAPIError(Exception):
    """Represents an error response returned from the Schwab API."""

    def __init__(
        self,
        *,
        status_code: int,
        url: str,
        body: str,
    ) -> None:
        super().__init__(
            f"Schwab API request failed; status={status_code}; url={url}; body={body}"
        )


async def call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> JSONType:
    """Call a Schwab client endpoint and return its JSON payload."""

    response = await func(*args, **kwargs)
    try:
        response.raise_for_status()
    except Exception as exc:
        raise SchwabAPIError(
            status_code=response.status_code,
            url=response.url,
            body=response.text,
        ) from exc

    # Handle responses with no content
    # 204 No Content: explicit no-content response
    # 201 Created: order placement endpoints return empty body with Location header
    status_code = getattr(response, "status_code", None)
    if status_code in (201, 204):
        return None

    # Check if response has content before trying to parse JSON
    # Some endpoints (like place_order) return empty bodies even with 2xx status
    content = getattr(response, "content", b"")
    if not content or len(content) == 0:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Expected JSON response from Schwab endpoint") from exc


__all__ = ["call", "JSONType", "SchwabAPIError"]
