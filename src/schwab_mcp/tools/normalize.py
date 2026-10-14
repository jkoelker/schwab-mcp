"""Helpers for normalizing tool result payloads before they reach callers."""

from __future__ import annotations

from schwab_mcp.tools.utils import JSONType


def strip_noise(data: JSONType) -> JSONType:
    """Recursively remove None, "", and {} values from a JSON-like structure.

    Never strips 0, 0.0, or False -- these are meaningful values in financial
    payloads (e.g. volume: 0, inTheMoney: false). Empty lists are also
    preserved, since they represent a meaningful "known empty" result (e.g.
    candles: [], positions: []) rather than an absent field.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            stripped = strip_noise(v)
            if stripped is None or stripped == "":
                continue
            if isinstance(stripped, dict) and stripped == {}:
                continue
            result[k] = stripped
        return result
    if isinstance(data, list):
        items = []
        for item in data:
            stripped = strip_noise(item)
            if stripped is None or stripped == "":
                continue
            if isinstance(stripped, dict) and stripped == {}:
                continue
            items.append(stripped)
        return items
    return data


__all__ = ["strip_noise"]
