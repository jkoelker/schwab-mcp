# Schwab Model Context Protocol Server

The **Schwab Model Context Protocol (MCP) Server** connects your Schwab account to LLM-based applications (like Claude Desktop or other MCP clients), allowing them to retrieve market data, check account status, and (optionally) place orders under your supervision.

## Features

*   **Market Data**: Real-time quotes, price history, option chains, and market movers.
*   **Account Management**: View balances, positions, and transactions.
*   **Trading**: comprehensive support for equities and options, including complex strategies (OCO, Bracket).
*   **Safety First**: Critical actions (like trading) are gated behind a **Discord approval workflow** by default.
*   **LLM Integration**: Designed specifically for Agentic AI workflows.

## Quick Start

### Prerequisites

*   Python 3.10 or higher
*   [uv](https://github.com/astral-sh/uv) (recommended) or `pip`
*   A Schwab Developer App Key and Secret (from the [Schwab Developer Portal](https://developer.schwab.com/))

### Installation

For most users, installing via `uv tool` or `pip` is easiest:

```bash
# Using uv (recommended for isolation)
uv tool install git+https://github.com/jkoelker/schwab-mcp.git

# Using pip
pip install git+https://github.com/jkoelker/schwab-mcp.git
```

### Authentication

Before running the server, you must authenticate with Schwab to generate a token file.

```bash
# If installed via uv tool
schwab-mcp auth --client-id YOUR_KEY --client-secret YOUR_SECRET --callback-url https://127.0.0.1:8182

# If running from source
uv run schwab-mcp auth --client-id YOUR_KEY --client-secret YOUR_SECRET --callback-url https://127.0.0.1:8182
```

This will open a browser window for you to log in to Schwab. Once complete, a token will be saved to `~/.local/share/schwab-mcp/token.yaml`.

### Running the Server

Start the MCP server to expose the tools to your MCP client.

```bash
# Basic Read-Only Mode (Safest)
schwab-mcp server --client-id YOUR_KEY --client-secret YOUR_SECRET

# Streamable HTTP (for reverse proxies / remote MCP connectors)
schwab-mcp server --client-id YOUR_KEY --client-secret YOUR_SECRET \
  --http --host 127.0.0.1 --port 8000

# With Trading Enabled (Requires Discord Approval)
schwab-mcp server \
  --client-id YOUR_KEY \
  --client-secret YOUR_SECRET \
  --discord-token BOT_TOKEN \
  --discord-channel-id CHANNEL_ID \
  --discord-approver YOUR_USER_ID
```

Default transport is **stdio** (Claude Desktop and most local MCP clients).
Use `--http` for FastMCP streamable-http when fronting the server with a
gateway or remote connector (MCP endpoint is `/mcp` on the bound host:port).

> **Note**: For trading capabilities, you must set up a Discord bot for approvals. See [Discord Setup Guide](docs/discord-setup.md).

## Configuration

You can configure the server using CLI flags or Environment Variables.

| Flag | Env Variable | Description |
|------|--------------|-------------|
| `--client-id` | `SCHWAB_CLIENT_ID` | **Required**. Schwab App Key. |
| `--client-secret` | `SCHWAB_CLIENT_SECRET` | **Required**. Schwab App Secret. |
| `--callback-url` | `SCHWAB_CALLBACK_URL` | Redirect URL (default: `https://127.0.0.1:8182`). |
| `--token-path` | N/A | Path to save/load token (default: `~/.local/share/...`). |
| `--http` | N/A | Use streamable-http transport instead of stdio. |
| `--host` | `MCP_HOST` | Bind address when using `--http` (default: `127.0.0.1`). |
| `--port` | `MCP_PORT` | Bind port when using `--http` (default: `8000`). |
| `--jesus-take-the-wheel`| N/A | **DANGER**. Bypasses Discord approval for trades. |
| `--no-technical-tools` | N/A | Disables technical analysis tools (SMA, RSI, etc.). |
| `--json` | N/A | Returns JSON instead of formatted text (useful for some agents). Null/empty fields are stripped to reduce token usage. |

### Container Usage

A Docker/Podman image is available at `ghcr.io/jkoelker/schwab-mcp`.

```bash
podman run --rm -it \
  --env SCHWAB_CLIENT_ID=... \
  --env SCHWAB_CLIENT_SECRET=... \
  -v ~/.local/share/schwab-mcp:/schwab-mcp \
  ghcr.io/jkoelker/schwab-mcp:latest server --token-path /schwab-mcp/token.yaml
```

## Available Tools

The server provides a rich set of tools for LLMs.

### 📊 Market Data
| Tool | Description |
|------|-------------|
| `get_quotes` | Real-time quotes for symbols. |
| `get_market_hours` | Market open/close times. |
| `get_movers` | Top gainers/losers for an index. |
| `get_option_chain` | Standard option chain data. |
| `get_price_history_*` | Historical candles (minute, day, week). |

### 💼 Account Info
| Tool | Description |
|------|-------------|
| `get_accounts` | List linked accounts (pass `include_positions=True` for holdings). |
| `get_account` | Balances for one account by hash (pass `include_positions=True` for holdings). |
| `get_transactions` | History of trades and transfers. |
| `get_orders` | Status of open and filled orders. |

### 💸 Trading (Requires Approval)
Placing an order is two steps: preview it, then place it by ID. Every
`preview_*` tool builds the order and calls Schwab's preview API to return
the projected order details plus a `preview_id`; `place_previewed_order`
then submits that exact previewed order — no re-derivation from parameters,
so the LLM can't hallucinate a different order than what was reviewed.

| Tool | Description |
|------|-------------|
| `preview_equity_order` | Preview a stock/ETF buy or sell. |
| `preview_option_order` | Preview an option contract buy or sell. |
| `preview_bracket_order` | Preview an entry + take-profit + stop-loss order. Stop-loss exit type defaults to `STOP`; pass `loss_type` (`STOP`, `STOP_LIMIT`, or `LIMIT`) for a different exit, plus `loss_limit_price` when `loss_type` is `STOP_LIMIT`; the response's `resolved_leg_types` shows what was actually built. |
| `place_previewed_order` | Place the exact order returned by a `preview_*` call, by `preview_id`. Requires approval. |
| `cancel_order` | Cancel an open order. |

*(See full tool list in `src/schwab_mcp/tools/`)*

## Development

To contribute to this project:

```bash
# Clone and install dependencies
git clone https://github.com/jkoelker/schwab-mcp.git
cd schwab-mcp
uv sync

# Run tests
uv run pytest

# Format and Lint
uv run ruff format . && uv run ruff check .
```

## License

MIT License.
