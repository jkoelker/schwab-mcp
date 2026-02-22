from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias


JSONPrimitive = str | int | float | bool | None
JSONType: TypeAlias = JSONPrimitive | dict[str, Any] | list[Any]


ResponseHandler: TypeAlias = Callable[[Any], tuple[bool, JSONType]]


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


def parse_date(value: str | datetime.date | None) -> datetime.date | None:
    """Parse a date from string, date, datetime, or None.

    Args:
        value: A date string in YYYY-MM-DD format, a date object,
               a datetime object, or None.

    Returns:
        A date object, or None if the input was None.
    """
    if value is None:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    return datetime.datetime.strptime(value, "%Y-%m-%d").date()


def parse_datetime(value: str | None) -> datetime.datetime | None:
    """Parse a datetime from an ISO format string or None.

    Args:
        value: An ISO format datetime string, or None.

    Returns:
        A datetime object, or None if the input was None.
    """
    return datetime.datetime.fromisoformat(value) if value is not None else None


async def call(
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    response_handler: ResponseHandler | None = None,
    **kwargs: Any,
) -> JSONType:
    """Call a Schwab client endpoint and return its JSON payload.

    When ``response_handler`` is provided, it can opt to handle the response
    by returning ``(True, payload)``. Returning ``(False, _)`` delegates back to
    the default JSON parsing behavior.
    """

    response = await func(*args, **kwargs)
    try:
        response.raise_for_status()
    except Exception as exc:
        body = response.text
        if not body:
            raw = getattr(response, "content", b"")
            body = (
                raw.decode("utf-8", errors="replace")
                if raw
                else f"HTTP {response.status_code}"
            )
        raise SchwabAPIError(
            status_code=response.status_code,
            url=response.url,
            body=body,
        ) from exc

    if response_handler is not None:
        handled, payload = response_handler(response)
        if handled:
            return payload

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


__all__ = [
    "call",
    "JSONType",
    "SchwabAPIError",
    "ResponseHandler",
    "parse_date",
    "parse_datetime",
]
