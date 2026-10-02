# src/schwab_mcp/approvals/

## Responsibility

Provides the approval abstraction and the Discord- and Signal-backed implementations used to gate Schwab write tools. The package defines a small backend interface (`ApprovalManager`), immutable request/decision types, a bypass manager for unrestricted mode, and the backend workflows that turn a write request into an approve/deny/expired decision.

## Design

- `base.py` owns the stable contract:
  - `ApprovalDecision` enum: `APPROVED`, `DENIED`, `EXPIRED`.
  - `ApprovalRequest`: frozen dataclass carrying approval id, tool name, MCP request/client ids, and stringified arguments shown to reviewers.
  - `ApprovalManager`: async lifecycle hooks (`start()`, `stop()`) plus abstract `require()`.
  - `NoOpApprovalManager`: always approves, used when writes are disabled or explicitly bypassed.
- `discord.py` implements `DiscordApprovalManager` around `discord.py`:
  - `DiscordApprovalSettings` stores token, channel id, allowed approver ids, and timeout.
  - `_ApprovalClient` is a thin `discord.Client` adapter that delegates readiness and reaction events back to the manager.
  - `_PendingApproval` ties an `ApprovalRequest`, Discord message, and `asyncio.Future[ApprovalDecision]` together while a reviewer is deciding.
- State is intentionally in-memory and process-local: a cached Discord channel, a pending-message map keyed by Discord message id, an async lock around pending state, and an event/task pair for bot readiness/lifecycle.
- The Discord manager requires at least one explicit approver id; unauthorized reactions are ignored and best-effort removed.
- `signal.py` implements `SignalApprovalManager` against a local bbernhard/signal-cli-rest-api daemon (which must run in `json-rpc`/`json-rpc-native` mode so `/v1/receive` is a websocket): approval requests are sent as Signal messages, decisions arrive as quoted replies ("ok"/"no") from authorized numbers quoting the bot's own message, per-tool renderers produce friendly one-line summaries (falling back to the shared `format_arguments` fenced dump), and oversized bodies are auto-denied. Argument values arrive repr-encoded from `_format_argument` (auto-wrapped tools) or as plain strings (`place_previewed_order`); the renderers decode both, derive the last-4 `account_hash` suffix themselves, and never display the full hash. `SignalApprovalSettings.account_names` maps last-4 suffixes to friendly account names.
- Shared rendering lives in `base.format_arguments()`: arguments in a fenced code block with backtick sanitization. Upstream `_format_argument` truncates each value at 256 chars before any backend sees it; beyond that, Discord truncates rendered output at 1000 chars while Signal auto-denies oversized bodies instead of truncating.

## Flow

1. The server lifecycle calls `approval_manager.start()` before exposing the MCPServer context and `stop()` during shutdown.
2. A write consumer builds an `ApprovalRequest` and calls `ApprovalManager.require()` (usually through `tools._registration.run_approval()`).
3. For Discord approvals, `require()` ensures the bot is connected and the configured channel is messageable, posts an orange pending embed, and adds ✅/❌ reactions.
4. The request is stored in `_pending` with a future. `require()` waits for that future with `timeout_seconds`.
5. `on_reaction_add` delegates to `_handle_reaction_add()`, which filters out bots, wrong channels/messages, unsupported emoji, and unauthorized users.
6. A valid ✅ sets `APPROVED`; a valid ❌ sets `DENIED`. The future is resolved first, with no await between the `done()` check and `set_result()`, so a second reaction or a timeout that arrives during the network edit cannot replace the recorded decision. Then the Discord message is edited to a final status embed including actor and notes. A failed edit is logged and does not change the decision.
7. If no valid decision arrives before the timeout, `require()` records `EXPIRED`, edits the message with timeout notes, removes pending state, and returns the decision.
8. If reaction setup fails, the manager finalizes the message as denied and returns `DENIED` so the write does not proceed silently.

## Integration

- `__init__.py` re-exports the approval API for the rest of the application.
- `cli.py` chooses the manager:
  - Discord settings are built from CLI/env inputs and enable write tools only when token, channel, and approvers are present.
  - Signal settings (`--signal-account`, `--signal-approver`, etc.) select `SignalApprovalManager` the same way; configuring both Discord and Signal at once is rejected.
  - `--jesus-take-the-wheel` selects `NoOpApprovalManager`, enables write tools, and warns that approvals are bypassed.
  - Without a configured backend or bypass mode, `NoOpApprovalManager` is still provided to the server, but write tools are not registered.
- `server.py` receives an `ApprovalManager`, starts/stops it in the MCPServer lifespan, and stores it in `SchwabServerContext`.
- `context.py` exposes the active manager as `SchwabContext.approvals` for tool code.
- `tools/_registration.py` is the primary consumer for automatically gated write tools: `register_tool(..., write=True)` wraps the function, creates an `ApprovalRequest` from formatted call arguments, reports MCP progress while waiting, calls `context.approvals.require()`, and only invokes the tool on `APPROVED`; `DENIED` raises `PermissionError`, `EXPIRED` raises `TimeoutError`.
- `tools/orders.py` is a specialized consumer: `place_previewed_order()` builds its own request using the cached preview summary instead of raw arguments, then uses `run_approval()` directly before placing the order. Automatic wrapping is bypassed for that tool while preserving destructive/write annotations.
