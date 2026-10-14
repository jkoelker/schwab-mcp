"""Date and datetime parsing helpers shared by tool modules."""

from __future__ import annotations

import datetime


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


__all__ = ["parse_date", "parse_datetime"]
