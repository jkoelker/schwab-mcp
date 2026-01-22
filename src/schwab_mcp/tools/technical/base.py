from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Annotated, Any, Iterable, Mapping, TypeAlias, cast

import pandas as pd

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools.utils import JSONType, call

from . import pandas_ta as _pandas_ta

__all__ = [
    "normalize_interval",
    "fetch_price_frame",
    "series_to_json",
    "frame_to_json",
    "ensure_columns",
    "compute_window",
    "pandas_ta",
    "Symbol",
    "Interval",
    "StartTime",
    "EndTime",
    "Points",
]

Symbol: TypeAlias = Annotated[str, "Symbol of the security"]

Interval: TypeAlias = Annotated[
    str,
    "Price interval. Supported values: 1m, 5m, 10m, 15m, 30m, 1d, 1w.",
]

StartTime: TypeAlias = Annotated[
    str | None,
    (
        "Optional ISO-8601 timestamp for the first candle used in the calculation. "
        "Defaults to enough history based on the requested parameters."
    ),
]

EndTime: TypeAlias = Annotated[
    str | None,
    "Optional ISO-8601 timestamp for the final candle (defaults to now in UTC).",
]

Points: TypeAlias = Annotated[
    int | None,
    (
        "Limit the number of indicator values returned. Defaults to the primary "
        "length parameter. Use a larger number to inspect more history."
    ),
]


@dataclass(frozen=True)
class _IntervalConfig:
    method_name: str
    bar_size: _dt.timedelta


_INTERVAL_CONFIGS: dict[str, _IntervalConfig] = {
    "1m": _IntervalConfig(
        method_name="get_price_history_every_minute",
        bar_size=_dt.timedelta(minutes=1),
    ),
    "5m": _IntervalConfig(
        method_name="get_price_history_every_five_minutes",
        bar_size=_dt.timedelta(minutes=5),
    ),
    "10m": _IntervalConfig(
        method_name="get_price_history_every_ten_minutes",
        bar_size=_dt.timedelta(minutes=10),
    ),
    "15m": _IntervalConfig(
        method_name="get_price_history_every_fifteen_minutes",
        bar_size=_dt.timedelta(minutes=15),
    ),
    "30m": _IntervalConfig(
        method_name="get_price_history_every_thirty_minutes",
        bar_size=_dt.timedelta(minutes=30),
    ),
    "1d": _IntervalConfig(
        method_name="get_price_history_every_day",
        bar_size=_dt.timedelta(days=1),
    ),
    "1w": _IntervalConfig(
        method_name="get_price_history_every_week",
        bar_size=_dt.timedelta(days=7),
    ),
}


def normalize_interval(value: str) -> str:
    """Return canonical short form (e.g., 1d, 15m) for the supplied interval."""

    normalized = value.strip().lower()
    if normalized in _INTERVAL_CONFIGS:
        return normalized
    raise ValueError(
        f"Unsupported interval '{value}'. "
        f"Choose from: {', '.join(sorted(_INTERVAL_CONFIGS))}"
    )


def _add_utc_timezone(value: _dt.datetime) -> _dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc)


def _parse_timestamp(value: str | _dt.datetime | None) -> _dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return _add_utc_timezone(value)
    return _add_utc_timezone(_dt.datetime.fromisoformat(value))


def _default_start(
    *, end: _dt.datetime, interval: _IntervalConfig, bars: int | None
) -> _dt.datetime | None:
    if bars is None or bars <= 0:
        return None
    return end - (interval.bar_size * bars)


def _candles_to_dataframe(candles: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(candles)
    if frame.empty:
        return frame

    if "datetime" in frame.columns:
        frame["datetime"] = pd.to_datetime(
            frame["datetime"], unit="ms", utc=True, errors="coerce"
        )
        frame = frame.dropna(subset=["datetime"]).set_index("datetime")

    numeric_columns = [
        column
        for column in ("open", "high", "low", "close", "volume")
        if column in frame.columns
    ]
    if numeric_columns:
        frame[numeric_columns] = frame[numeric_columns].apply(
            pd.to_numeric, errors="coerce"
        )

    return frame.sort_index().dropna(how="all")


def ensure_columns(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            "Price history missing required columns: " + ", ".join(sorted(missing))
        )


def compute_window(length: int, *, multiplier: int = 3, min_padding: int = 20) -> int:
    return max(length * multiplier, length + min_padding)


async def fetch_price_frame(
    ctx: SchwabContext,
    symbol: str,
    *,
    interval: str,
    start: str | None = None,
    end: str | None = None,
    bars: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch OHLCV data for the requested interval and return a pandas DataFrame."""
    interval_key = normalize_interval(interval)
    config = _INTERVAL_CONFIGS[interval_key]

    end_dt = _parse_timestamp(end) or _dt.datetime.now(tz=_dt.timezone.utc)
    start_dt = _parse_timestamp(start) or _default_start(
        end=end_dt, interval=config, bars=bars
    )

    fetcher = getattr(ctx.price_history, config.method_name)
    response: JSONType = await call(
        fetcher,
        symbol,
        start_datetime=start_dt,
        end_datetime=end_dt,
    )
    if not isinstance(response, Mapping):
        raise TypeError("Unexpected response type for price history payload")

    candles = response.get("candles", [])
    frame = _candles_to_dataframe(candles)

    empty = bool(response.get("empty")) or frame.empty

    metadata = {
        "symbol": str(response.get("symbol", symbol)).upper(),
        "interval": interval_key,
        "start": start_dt.isoformat() if start_dt else None,
        "end": end_dt.isoformat(),
        "bars_requested": bars,
        "empty": empty,
        "candles_returned": len(frame),
    }
    return frame, metadata


def series_to_json(
    series: pd.Series,
    *,
    limit: int | None = None,
    value_key: str | None = None,
) -> list[dict[str, Any]]:
    """Convert a pandas Series indexed by timestamps into JSON serializable rows."""

    if series.empty:
        return []

    series = series.dropna()
    if series.empty:
        return []

    if limit is not None and limit > 0:
        series = series.tail(limit)

    value_key = value_key or (str(series.name) if series.name else "value")

    index = _normalize_index(series.index)
    values = series.to_numpy()

    rows: list[dict[str, Any]] = []
    for timestamp, value in zip(index, values):
        if pd.isna(timestamp) or pd.isna(value):
            continue

        rows.append({"timestamp": timestamp.isoformat(), value_key: float(value)})

    return rows


def frame_to_json(
    frame: pd.DataFrame,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame indexed by timestamps into JSON rows."""

    if frame.empty:
        return []

    numeric = frame.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.dropna(how="all")
    if numeric.empty:
        return []

    if limit is not None and limit > 0:
        numeric = numeric.tail(limit)

    index = _normalize_index(numeric.index)
    rows: list[dict[str, Any]] = []
    for timestamp, (_, row) in zip(index, numeric.iterrows()):
        valid_items = {
            str(column): float(value)
            for column, value in row.items()
            if pd.notna(value)
        }
        if not valid_items:
            continue
        rows.append({"timestamp": timestamp.isoformat(), **valid_items})

    return rows


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    if isinstance(index, pd.DatetimeIndex):
        if index.tz is None:
            return index.tz_localize("UTC")
        return index.tz_convert("UTC")

    converted = pd.to_datetime(index, utc=True, errors="coerce")
    if not isinstance(converted, pd.DatetimeIndex):
        converted = pd.DatetimeIndex(converted)
    return converted


# Re-export the optional dependency so submodules can share the import guard.
pandas_ta = cast(Any, _pandas_ta)
