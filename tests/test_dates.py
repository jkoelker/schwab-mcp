"""Tests for date and datetime parsing helpers."""

from __future__ import annotations

import datetime

from schwab_mcp.tools._dates import parse_datetime


def run(coro):
    import asyncio

    return asyncio.run(coro)


class TestParseDatetimeFunction:
    def test_parse_datetime_with_none(self):
        assert parse_datetime(None) is None

    def test_parse_datetime_with_iso_string(self):
        result = parse_datetime("2024-03-15T10:30:00")
        assert result == datetime.datetime(2024, 3, 15, 10, 30)

    def test_parse_datetime_with_date_only_string(self):
        result = parse_datetime("2024-03-15")
        assert result == datetime.datetime(2024, 3, 15, 0, 0)
