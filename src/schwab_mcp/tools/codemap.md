# src/schwab_mcp/tools/

## Responsibility

MCP tool layer for the Schwab API. It exposes read-only market/account data,
transaction and order lookup, option chains, price history, and gated order
actions through FastMCP tools. Modules keep Schwab client calls small and typed,
normalize user-friendly string/date inputs, and shape large Schwab payloads into
compact defaults with `verbose=True` escape hatches where response size matters.

## Design

- `__init__.py` is the aggregator: `register_tools()` calls each module's
  `register()` and conditionally adds `technical/` tools when enabled.
- `_registration.py` centralizes FastMCP registration. `register_tool()` converts
  MCP `Context` arguments into `SchwabContext`, attaches read/write annotations,
  applies optional `result_transform`, and wraps write tools in the approval
  workflow unless a tool supplies custom approval handling.
- `_protocols.py` defines Protocol facades for each Schwab client namespace
  (`accounts`, `orders`, `quotes`, `options`, `price_history`, etc.). These keep
  `SchwabContext` access type-checkable without coupling tool code to concrete
  schwab-py implementations.
- `utils.py` owns shared parsing and API behavior: `call()` awaits Schwab client
  methods, raises `SchwabAPIError` with status/url/body on non-2xx responses,
  handles empty 201/204 bodies, supports endpoint-specific response handlers,
  and returns the JSON type alias used by all tools.
- Response shaping is intentionally local to each domain: accounts prune balances
  and positions while enriching hashes/nicknames, quotes keep key quote fields,
  options prune per-contract greeks/liquidity fields and default expiration
  windows to 60 days, and orders prune nested order payloads recursively.
- Order construction is split between `orders.py` orchestration and
  `order_helpers.py` builder factories. Helpers return configured schwab-py
  `OrderBuilder` instances for equity, option, stop/limit, and trailing-stop
  primitives; `orders.py` validates user parameters and composes single, OCO,
  trigger, bracket, and option-combo specs.

## Flow

1. Server startup calls `register_tools(server, client, allow_write, ...)`.
2. Each module registers its read-only tuple through `register_tool()`; `orders`
   only registers write tools when `allow_write=True`.
3. At invocation, FastMCP passes an MCP context. Registration wrappers convert it
   to `SchwabContext`, whose typed Protocol-backed properties expose the relevant
   Schwab client facade.
4. Tool functions parse strings/dates, map enum names through Schwab client
   namespaces, and call Schwab endpoints via `await call(...)`.
5. Raw JSON is returned directly for simple endpoints or pruned/enriched before
   returning to the MCP caller. Compact mode is the default for high-volume
   accounts, quotes, options, and orders.
6. Order preview tools build an exact order spec, submit Schwab `preview_order`,
   cache the spec in `ctx.previews`, and return `preview_id` plus reviewer/user
   action text. `place_previewed_order()` consumes that cached spec, creates a
   custom approval request with a human-readable summary, places the exact order,
   and returns compact post-placement order status. `cancel_order()` uses the
   generic write-tool approval wrapper.

## Integration

- Depends on `schwab_mcp.context.SchwabContext` for per-request access to the
  Schwab async client facades, approval manager, preview cache, request metadata,
  and progress/warning reporting.
- Uses FastMCP's `server.tool()` through `_registration.register_tool()` so tool
  docs, annotations, and parameter metadata come from Python signatures/docstrings.
- Integrates with `schwab_mcp.approvals` for write safeguards: automatic approval
  wrapping for simple writes and explicit approval requests for previewed order
  placement.
- Integrates with schwab-py enums, order builders, and option symbol helpers but
  shields callers from most enum/object details by accepting strings/lists/dates.
- `technical/` is an optional child package registered by this folder's
  aggregator; it reuses `ctx.price_history` and `call()` to compute derived
  indicators from Schwab candle data when `pandas_ta_classic` is installed.
