"""Datetime parsing helpers shared by tool modules."""

from __future__ import annotations

import datetime


def parse_datetime(value: str | None) -> datetime.datetime | None:
    """Parse a datetime from an ISO format string or None.

    Args:
        value: An ISO format datetime string, or None.

    Returns:
        A datetime object, or None if the input was None.
    """
    return datetime.datetime.fromisoformat(value) if value is not None else None


__all__ = ["parse_datetime"]
