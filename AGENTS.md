# Repository Guidelines

## Project Structure

```
src/schwab_mcp/
  __init__.py         # Entry point proxy
  cli.py              # Click CLI commands (auth, server)
  server.py           # SchwabMCPServer class, FastMCP integration
  context.py          # SchwabContext, SchwabServerContext dataclasses
  auth.py             # OAuth browser flow helpers
  tokens.py           # Token load/save, validation
  approvals/          # Discord approval workflow
  db/                 # Cloud SQL Postgres integration
    __init__.py       # DatabaseManager, CloudSQLManager exports
    _manager.py       # Connection management, reconnect logic
    _schema.py        # DDL for option chain storage
    _ingestion.py     # Option chain data ingestion
  remote/             # Cloud Run remote server
    __init__.py
    app.py            # Starlette app: OAuth + MCP streamable HTTP
    config.py         # RemoteServerConfig, AdminConfig (from env vars)
    oauth.py          # OAuth 2.1 provider for claude.ai auth
    token_storage.py  # Postgres-backed Schwab token storage + cache
  admin/              # Admin service for Schwab re-auth
    __init__.py
    app.py            # Starlette app: dashboard + Schwab OAuth flow
  tools/              # MCP tool implementations
    __init__.py       # register_tools() aggregator
    _registration.py  # register_tool(), approval wrapping
    _protocols.py     # Protocol classes for typed client facades
    utils.py          # call() helper, SchwabAPIError, JSONType
    tools.py          # get_datetime, get_market_hours, get_movers
    account.py        # Account and preferences tools
    history.py        # Price history tools
    options.py        # Option chain tools
    orders.py         # Order placement and management
    order_helpers.py  # Order builder factories
    quotes.py         # Quote retrieval tools
    transactions.py   # Transaction history tools
    technical/        # Optional pandas-ta indicators (sma, rsi, etc.)
docs/
  discord-setup.md    # Discord approval bot setup
  cloud-run-deployment.md  # Cloud Run deployment guide
tests/
  test_*.py           # Mirror source structure
```

## Build, Test, and Development Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run schwab-mcp --help
uv run schwab-mcp server --help

# Type checking
uv run pyright

# Format code (run before commits)
uv run ruff format .

# Lint (auto-fixable issues)
uv run ruff check .
uv run ruff check . --fix

# Run full test suite with coverage
uv run pytest

# Run a single test file
uv run pytest tests/test_tools.py

# Run a single test function
uv run pytest tests/test_tools.py::test_get_datetime_returns_eastern_time

# Run tests matching a pattern
uv run pytest -k "get_option"

# Run with verbose output
uv run pytest -v tests/test_orders.py

# Combined check before commit
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

## Code Style & Formatting

### Python Version and Imports
- Target Python 3.12+ (use `from __future__ import annotations` for forward refs)
- Use explicit imports, no wildcards
- Group imports: stdlib, third-party, local (ruff enforces this)
- Prefer `from schwab_mcp.tools import module` over `from schwab_mcp.tools.module import func`

```python
from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call
```

### Type Annotations
- All function signatures must be typed
- Use `Annotated[type, "description"]` for tool parameters (MCP uses these for descriptions)
- Use `JSONType` alias for Schwab API return values
- Use Protocol classes in `_protocols.py` for typed client facades
- Pyright is set to `basic` mode; don't fight it with `type: ignore`

```python
async def get_movers(
    ctx: SchwabContext,
    index: Annotated[str, "Index: DJI, COMPX, SPX, NYSE, NASDAQ"],
    sort: Annotated[str | None, "Sort: VOLUME, TRADES, PERCENT_CHANGE_UP/DOWN"] = None,
) -> JSONType:
    """Get top 10 movers for an index/market."""
    ...
```

### Naming Conventions
- Module files: `snake_case.py`
- Classes: `CamelCase` (e.g., `SchwabContext`, `SchwabMCPServer`)
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers: prefix with `_` (e.g., `_build_equity_order_spec`)
- Tool functions: match Schwab API naming (e.g., `get_market_hours`, `place_equity_order`)

### Error Handling
- Use `SchwabAPIError` for API failures (defined in `tools/utils.py`)
- Raise `ValueError` for invalid parameters
- Raise `PermissionError` for denied approvals
- Raise `TimeoutError` for expired approvals
- Let unexpected exceptions propagate (don't catch-all)

```python
if order_type not in _EQUITY_ORDER_TYPES:
    raise ValueError(
        f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT, STOP, STOP_LIMIT"
    )
```

### Async Patterns
- All tool functions are `async`
- Use `await call(client.method, ...)` to invoke Schwab client methods
- The `call()` helper handles response parsing and error wrapping

## Testing Guidelines

### Test File Organization
- Name test files `test_<module>.py` in the `tests/` directory
- Name test functions `test_<behavior>` (descriptive, not `test_1`)
- Use `monkeypatch` to stub `call()` or client methods

### Test Fixtures Pattern
```python
class DummyApprovalManager(ApprovalManager):
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.APPROVED

def make_ctx(client: Any) -> SchwabContext:
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=DummyApprovalManager(),
    )
    request_context = SimpleNamespace(lifespan_context=lifespan_context)
    return SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )

def run(coro):
    return asyncio.run(coro)
```

### Mocking Schwab Client
```python
def test_get_market_hours_handles_string_inputs(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(tools, "call", fake_call)

    client = DummyToolsClient()
    ctx = make_ctx(client)
    result = run(tools.get_market_hours(ctx, "equity, option", date="2024-03-01"))

    assert result == "ok"
    assert captured["kwargs"]["date"] == datetime.date(2024, 3, 1)
```

### Coverage
- Tests run with `--cov=schwab_mcp --cov-report=term-missing`
- Aim to cover error branches that raise MCP errors or touch token handling

## Security & Configuration

- Store credentials via environment variables or `.env` files
- Required: `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_CALLBACK_URL`
- Never commit tokens from `~/.local/share/schwab-mcp/`
- Changes enabling `--jesus-take-the-wheel` require documented safeguards

## Commit Message Format

Follow Linux kernel style with conventional commits:

### Subject Line (50 chars max, 72 absolute max)
- Imperative mood: "Add feature" not "Added feature"
- Format: `type(scope): description`
- Types: `fix`, `feat`, `chore`, `refactor`, `test`, `perf`, `docs`
- Scopes: `tools`, `cli`, `server`, `auth`, `approvals`, `deps`
- No period at end

### Body (wrap at 72 chars)
- Explain *what* and *why*, not *how*
- Use prose, not bullet points
- Reference issues at the bottom

### Examples
```
feat(tools): add trailing stop order support

Order placement previously only supported market, limit, stop, and
stop-limit orders. Users frequently need trailing stops for automated
risk management.

Add place_equity_trailing_stop_order() and supporting builder functions.
Include tests for VALUE and PERCENT trail types.

Closes #23
```

```
fix(options): default date window to 60 days

Option chain requests without date parameters returned all expirations,
causing oversized responses that exceeded context limits.

Default from_date to today and to_date to today + 60 days when both
are omitted. This matches typical option trading horizons.
```
