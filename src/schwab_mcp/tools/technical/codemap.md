# src/schwab_mcp/tools/technical/

## Responsibility

Optional technical-analysis MCP tools. They fetch Schwab price history, convert
candles into pandas frames, compute indicators, and return compact JSON rows for
recent values. Available indicators include moving averages, RSI/stochastic,
MACD/ATR/ADX, VWAP/Bollinger/pivot points, historical volatility, and expected
move helpers.

## Design

- `__init__.py` is an optional-dependency gate. It imports
  `pandas_ta_classic` once, exposes it as `pandas_ta`, and skips all technical
  registration when the package is missing. If present, it lazily imports and
  registers the indicator modules.
- Each indicator module has a `register()` function and uses the parent
  `_registration.register_tool()` path, so MCP context conversion, annotations,
  and result transforms behave the same as non-technical tools. All tools are
  read-only; `allow_write` is ignored.
- `base.py` provides the shared indicator pipeline: interval normalization,
  Schwab price-history fetches, candle-to-DataFrame conversion, required-column
  validation, warm-up window sizing, and JSON serialization.
- `compute_series_indicator()` and `compute_frame_indicator()` reduce repeated
  logic for pandas-ta indicators, enforcing Series/DataFrame expectations,
  dropping warm-up nulls, limiting output rows via `points`, and returning common
  metadata (`symbol`, `interval`, `start`, `end`, `candles`, parameters).
- Not every calculation is delegated to pandas-ta: pivot points are implemented
  directly because the pinned `pandas_ta_classic` versions do not expose a
  compatible pivot-point function. Volatility tools use pandas/numpy math for
  domain-specific statistics and compact summaries.

## Flow

1. Parent `tools.register_tools(..., enable_technical=True)` calls
   `technical.register()`.
2. `technical.register()` returns immediately if `pandas_ta_classic` is not
   installed; otherwise it imports `moving_average`, `momentum`, `trend`,
   `overlays`, and `volatility`, then calls each module's `register()`.
3. An indicator invocation validates local parameters and computes a padded bar
   window with `compute_window()` or tool-specific sizing.
4. `fetch_price_frame()` maps intervals (`1m`, `5m`, `10m`, `15m`, `30m`, `1d`,
   `1w`) to the matching `ctx.price_history` convenience method, calls it through
   `call()`, converts the returned `candles` list into a time-indexed OHLCV
   DataFrame, and records fetch metadata.
5. The indicator function computes one or more pandas Series, null warm-up rows
   are dropped, and `series_to_json()`/`frame_to_json()` returns only recent rows
   (default up to three, controlled by `points`) with ISO UTC timestamps and
   rounded numeric values.

## Integration

- Registered only through `src/schwab_mcp/tools/__init__.py`; disabling technical
  tools or omitting `pandas_ta_classic` leaves the rest of the Schwab tools
  unaffected.
- Uses `SchwabContext.price_history`, whose client surface is described by the
  Protocol facades in `tools/_protocols.py`, and uses the shared `call()` helper
  for consistent Schwab error handling and JSON extraction.
- Shares FastMCP registration behavior with the parent tool package, including
  context wrapping and optional result transformation.
- Produces compact, model-friendly responses instead of raw candles or pandas
  objects: metadata plus recent computed values. Callers that need more output
  increase `points`; callers that need more calculation history pass explicit
  `start`/`end` or volatility `bars` where supported.
