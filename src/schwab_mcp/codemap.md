# `src/schwab_mcp/`

## Responsibility

`schwab_mcp` is the application package for a Schwab-backed MCP server. It owns the public entry point, CLI commands, OAuth/token lifecycle, FastMCP server construction, request context model, static MCP resources, and in-memory order preview cache. Tool implementations live under `schwab_mcp.tools`, and approval backends live under `schwab_mcp.approvals`; this directory wires those subpackages into the runtime.

## Design

- `__init__.py`: exposes `main()` as a lazy proxy to `schwab_mcp.cli.main`, avoiding eager import of Click and server dependencies for package importers.
- `cli.py`: Click command surface. `auth` performs interactive OAuth token creation, `server` starts the MCP server, and `save-credentials` writes local Schwab API credentials. It validates required credentials before server startup and reports pre-initialization failures through MCP JSON-RPC error payloads.
- `auth.py`: adapter around `schwab.auth`. `easy_client()` loads an existing token through a local `tokens.Manager`, rejects tokens older than `DEFAULT_MAX_TOKEN_AGE_SECONDS` when configured, or falls back to `client_from_login_flow()`. The login flow only permits `127.0.0.1` callback hosts and runs the redirect listener in a `multiprocess.Process`.
- `tokens.py`: filesystem persistence layer. `token_path()` and `credentials_path()` resolve files under `platformdirs.user_data_dir`; `token_writer()`/`token_loader()` support YAML and JSON token files; `save_credentials()` writes YAML credentials with `0o600` permissions; `Manager` binds a token path to schwab-py-compatible load/write callables.
- `server.py`: FastMCP adapter. `SchwabMCPServer` constructs `FastMCP`, installs `_client_lifespan()`, registers tools/resources, and chooses a result transform: Toon-encoded stripped payloads by default or stripped JSON when `use_json=True`. `send_error_response()` emits JSON-RPC 2.0 errors to stdout before the MCP server is initialized.
- `context.py`: typed dependency container. `SchwabServerContext` stores the raw `AsyncClient`, `ApprovalManager`, `PreviewStore`, and typed client facades cast from `schwab_mcp.tools._protocols`. `SchwabContext` subclasses FastMCP `Context` and exposes safe properties for tools.
- `resources.py`: static MCP reference resource registry for order statuses, order types/workflows, option symbol formats, and trading sessions. `register_resources()` binds them to `schwab://reference/...` URIs.
- `previews.py`: TTL cache for the two-step order workflow. `PreviewStore.put()` deep-copies an order spec and returns a cryptographically random 16-character hex ID; `pop()` validates expiry and account hash, deletes on use, and returns the stored `PreviewEntry`.

Key architectural patterns are lifespan-scoped dependency injection, protocol-based facades over the Schwab client, command-line dependency assembly, explicit pre-server error reporting, result transformation at registration time, and preview-then-place order safety.

## Flow

1. Console execution enters `schwab_mcp.__init__.main()`, which imports and calls `cli.main()`.
2. `cli.auth()` resolves `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, and callback/base URLs from options, environment, or `tokens.load_credentials()`, then calls `auth.easy_client(..., interactive=True)` to create and persist a token.
3. `cli.server()` resolves credentials, creates a `tokens.Manager`, calls `auth.easy_client(..., asyncio=True, interactive=False, enforce_enums=False)`, verifies the result is `schwab.client.AsyncClient`, and rejects tokens older than five days.
4. The server command selects write permissions: `--jesus-take-the-wheel` uses `NoOpApprovalManager` and enables writes; Discord configuration creates `DiscordApprovalManager`; otherwise writes are disabled and a no-op manager is still used for lifecycle consistency.
5. `SchwabMCPServer.__init__()` creates `FastMCP` with `_client_lifespan()`, registers all tools via `tools.register_tools()` with write/technical/result-transform flags, then registers resources via `resources.register_resources()`.
6. On FastMCP startup, `_client_lifespan()` starts the approval manager and yields `SchwabServerContext`. Tool registration wrappers in `schwab_mcp.tools._registration` convert generic MCP contexts to `SchwabContext`, apply approval gating for write tools, and apply the configured result transform.
7. During tool execution, code accesses Schwab APIs through `ctx.accounts`, `ctx.orders`, `ctx.quotes`, `ctx.options`, `ctx.price_history`, `ctx.transactions`, or `ctx.tools`; order placement tools use `ctx.previews` for preview IDs and exact-spec execution.
8. On shutdown, `_client_lifespan()` stops the approval manager and closes the Schwab async client session, logging cleanup failures without masking shutdown.

## Integration

- Entry points: `schwab_mcp.main()`, Click commands in `cli.py`, and `SchwabMCPServer.run()` for FastMCP stdio transport.
- Schwab integration: `auth.py` delegates to `schwab.auth` and returns `schwab.client.Client` or `AsyncClient`; server mode requires `AsyncClient` and passes it through typed facades in `context.py`.
- MCP integration: `server.py` uses `mcp.server.fastmcp.FastMCP`; `context.py` subclasses FastMCP `Context`; `resources.py` registers URI-addressable resources; `tools.register_tools()` registers callable Schwab operations.
- Approval integration: `cli.py` constructs either `NoOpApprovalManager` or `DiscordApprovalManager`; `server._client_lifespan()` owns start/stop; `tools._registration.register_tool()` wraps write tools with approval requests and progress reporting.
- Persistence/security integration: `tokens.py` stores OAuth tokens and credentials in the user data directory, supports YAML/JSON tokens, and uses restricted file modes for sensitive data.
- Output integration: server results are normalized with `schwab_mcp.tools.utils.strip_noise`; non-JSON mode requires `toon.encode` to produce compact string payloads for MCP clients.
