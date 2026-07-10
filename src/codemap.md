# `src/`

## Responsibility

`src/` contains the installable Python package for the Schwab Model Context Protocol server. Its only application package is `schwab_mcp`, which exposes a Click CLI, Schwab OAuth/token management, a FastMCP stdio server, request context wiring, static MCP resources, order preview caching, approval-gated write tooling, and registered Schwab API tools.

## Design

- `src/schwab_mcp/__init__.py` is the package entry point proxy; `main()` lazily imports `schwab_mcp.cli.main` so importing the package does not eagerly load CLI dependencies.
- `src/schwab_mcp/cli.py` is the command boundary. It resolves credentials from flags, environment variables, and local credential files, then creates authenticated Schwab clients and server dependencies.
- `src/schwab_mcp/server.py` adapts a Schwab `AsyncClient` into a FastMCP server, using lifespan-scoped dependency injection and a tool result transform strategy: Toon encoding by default or stripped JSON with `--json`.
- `src/schwab_mcp/context.py` centralizes shared runtime state in `SchwabServerContext` and exposes typed protocol facades through `SchwabContext` properties.
- `src/schwab_mcp/auth.py` and `src/schwab_mcp/tokens.py` isolate OAuth browser flow, token caching, token age validation, and secure local credential/token persistence.
- `src/schwab_mcp/resources.py` registers static MCP reference resources. `src/schwab_mcp/previews.py` provides the in-memory TTL cache used by the order preview/place workflow.
- `src/schwab_mcp/tools/` and `src/schwab_mcp/approvals/` are subpackages referenced by the core package: tools register MCP callable functions, while approvals provide write-operation authorization backends.

## Flow

1. The console entry point calls `schwab_mcp.main()`, which delegates to `cli.main()`.
2. `schwab-mcp auth` loads stored credentials via `tokens.load_credentials()`, creates a `tokens.Manager`, and runs `auth.easy_client()` in interactive mode to write a Schwab OAuth token.
3. `schwab-mcp server` resolves credentials, creates an async Schwab client through `auth.easy_client(interactive=False, asyncio=True)`, checks token age, chooses an approval manager, and instantiates `SchwabMCPServer`.
4. `SchwabMCPServer` creates `FastMCP`, registers tool modules through `tools.register_tools()`, registers static resources through `resources.register_resources()`, and runs stdio transport.
5. During FastMCP lifespan startup, `server._client_lifespan()` starts the approval manager and yields `SchwabServerContext`; tool calls receive `SchwabContext`, which exposes the raw client, typed client facades, approvals, and preview store.
6. On shutdown, the lifespan finalizer stops the approval manager and closes the Schwab async HTTP session.

## Integration

- External APIs/libraries: `schwab-py` for OAuth and Schwab REST clients, `mcp.server.fastmcp.FastMCP` for MCP stdio serving, `click` for CLI commands, `anyio` for async execution, `platformdirs` and `yaml/json` for local persistence, and `toon` for compact tool payload encoding.
- Main entry points: package `main()` in `src/schwab_mcp/__init__.py`; CLI commands `auth`, `server`, and `save-credentials` in `src/schwab_mcp/cli.py`; server runtime `SchwabMCPServer.run()` in `src/schwab_mcp/server.py`.
- Security boundaries: credentials/tokens are stored under the user data directory with restricted permissions; server startup rejects missing credentials, stale tokens, non-async clients, and incomplete Discord approval configuration before serving MCP requests.
- Tool/resource integration: `server.py` wires the core runtime to `src/schwab_mcp/tools` for Schwab operations and to `resources.py` for reference data; write tools are gated by approval managers unless explicitly bypassed with `--jesus-take-the-wheel`.
