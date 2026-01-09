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

# With Trading Enabled (Requires Discord Approval)
schwab-mcp server \
  --client-id YOUR_KEY \
  --client-secret YOUR_SECRET \
  --discord-token BOT_TOKEN \
  --discord-channel-id CHANNEL_ID \
  --discord-approver YOUR_USER_ID
```

> **Note**: For trading capabilities, you must set up a Discord bot for approvals. See [Discord Setup Guide](docs/discord-setup.md).

## Configuration

You can configure the server using CLI flags or Environment Variables.

| Flag | Env Variable | Description |
|------|--------------|-------------|
| `--client-id` | `SCHWAB_CLIENT_ID` | **Required**. Schwab App Key. |
| `--client-secret` | `SCHWAB_CLIENT_SECRET` | **Required**. Schwab App Secret. |
| `--callback-url` | `SCHWAB_CALLBACK_URL` | Redirect URL (default: `https://127.0.0.1:8182`). |
| `--token-path` | N/A | Path to save/load token (default: `~/.local/share/...`). |
| `--jesus-take-the-wheel`| N/A | **DANGER**. Bypasses Discord approval for trades. |
| `--no-technical-tools` | N/A | Disables technical analysis tools (SMA, RSI, etc.). |
| `--json` | N/A | Returns raw JSON instead of formatted text (useful for some agents). |

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
| `get_accounts` | List linked accounts. |
| `get_account_positions` | Detailed positions and balances. |
| `get_transactions` | History of trades and transfers. |
| `get_orders` | Status of open and filled orders. |

### 💸 Trading (Requires Approval)
| Tool | Description |
|------|-------------|
| `place_equity_order` | Buy/Sell stocks and ETFs. |
| `place_option_order` | Buy/Sell option contracts. |
| `place_bracket_order` | Entry + Take Profit + Stop Loss. |
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
