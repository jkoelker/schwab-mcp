"""Tests for date and datetime parsing helpers."""

from __future__ import annotations

import datetime

from schwab_mcp.tools._dates import parse_date, parse_datetime


class TestParseDateFunction:
    def test_parse_date_with_none(self):
        assert parse_date(None) is None

    def test_parse_date_with_string(self):
        result = parse_date("2024-03-15")
        assert result == datetime.date(2024, 3, 15)

    def test_parse_date_with_date(self):
        input_date = datetime.date(2024, 3, 15)
        result = parse_date(input_date)
        assert result is input_date

    def test_parse_date_with_datetime(self):
        input_datetime = datetime.datetime(2024, 3, 15, 10, 30)
        result = parse_date(input_datetime)
        assert result == datetime.date(2024, 3, 15)


class TestParseDatetimeFunction:
    def test_parse_datetime_with_none(self):
        assert parse_datetime(None) is None

    def test_parse_datetime_with_iso_string(self):
        result = parse_datetime("2024-03-15T10:30:00")
        assert result == datetime.datetime(2024, 3, 15, 10, 30)

    def test_parse_datetime_with_date_only_string(self):
        result = parse_datetime("2024-03-15")
        assert result == datetime.datetime(2024, 3, 15, 0, 0)
