# Repository Atlas: schwab-mcp

## Project Responsibility

`schwab-mcp` is a Python MCP server that exposes Schwab brokerage data,
market data, option chains, price history, optional technical indicators, and
approval-gated order workflows to MCP clients. The repository packages a Click
CLI, Schwab OAuth/token persistence helpers, a FastMCP stdio server, static MCP
resources, typed request context facades, order preview caching, and Discord
approval infrastructure for write operations.

## System Entry Points

- `src/schwab_mcp/__init__.py`: package `main()` proxy for the console script.
- `src/schwab_mcp/cli.py`: Click commands for `auth`, `server`, and
  `save-credentials`.
- `src/schwab_mcp/server.py`: `SchwabMCPServer` construction, lifespan wiring,
  tool/resource registration, result transformation, and stdio serving.
- `src/schwab_mcp/tools/__init__.py`: MCP tool registration aggregator.
- `pyproject.toml`: package metadata, dependency groups, console script, and
  tool configuration.
- `Containerfile`: container runtime packaging for the MCP server.

## Directory Map

| Directory | Responsibility Summary | Detailed Map |
|-----------|------------------------|--------------|
| `src/` | Installable Python source tree containing the Schwab MCP server package and its CLI/runtime modules. | [View Map](src/codemap.md) |
| `src/schwab_mcp/` | Core application package: CLI, OAuth/token lifecycle, FastMCP server adapter, context model, static resources, and preview cache. | [View Map](src/schwab_mcp/codemap.md) |
| `src/schwab_mcp/approvals/` | Approval abstraction and Discord-backed approval workflow for Schwab write tools. | [View Map](src/schwab_mcp/approvals/codemap.md) |
| `src/schwab_mcp/tools/` | MCP tool layer that adapts Schwab API operations, response shaping, order builders, preview/place workflows, and write approvals. | [View Map](src/schwab_mcp/tools/codemap.md) |
| `src/schwab_mcp/tools/technical/` | Optional technical-analysis tools using Schwab price history and `pandas_ta_classic`/pandas calculations. | [View Map](src/schwab_mcp/tools/technical/codemap.md) |

## Root Assets

- `AGENTS.md`: repository-specific agent instructions, structure, commands,
  coding style, testing patterns, security notes, and commit format.
- `README.md`: user-facing setup and usage documentation.
- `pyproject.toml`: package metadata, dependencies, optional technical-analysis
  extras, ruff/pyright/pytest configuration, and console script definition.
- `uv.lock`: locked dependency graph for `uv` installs.
- `Makefile`: local helper targets for common project workflows.
- `Containerfile`: container image build recipe.
- `.pre-commit-config.yaml`: pre-commit hook configuration.
- `renovate.json`: dependency update automation configuration.

## High-Level Flow

1. Users run the console script, which calls `schwab_mcp.main()` and dispatches
   to Click command handlers.
2. Authentication commands resolve credentials, run Schwab OAuth through
   `schwab-py`, and persist tokens/credentials under the user data directory.
3. The `server` command creates an async Schwab client, validates token age,
   configures write-approval behavior, and instantiates `SchwabMCPServer`.
4. Server startup registers resources and MCP tools. FastMCP lifespan state
   injects the Schwab client, approval manager, and preview store into each tool
   call through `SchwabContext`.
5. Read tools call Schwab endpoints through typed facades and shared response
   parsing. Write tools either require generic approval wrapping or use the
   preview-then-place workflow for exact-spec order placement.

## Integration Points

- Schwab integration uses `schwab-py` clients, enums, OAuth helpers, and order
  builders.
- MCP integration uses `mcp.server.fastmcp.FastMCP`, FastMCP `Context`, static
  resources, tool annotations, and stdio transport.
- Approval integration uses a process-local `ApprovalManager` interface with a
  Discord implementation for human decisions and a no-op implementation for
  disabled/bypassed write modes.
- Optional analytics integration loads `pandas_ta_classic`, pandas, and numpy
  only when technical tools are enabled and available.
