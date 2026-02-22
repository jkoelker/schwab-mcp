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

*   Python 3.12 or higher
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

#### Standard Authentication (Automatic)

For most users with the standard callback URL (`https://127.0.0.1:8182`):

```bash
# If installed via uv tool
schwab-mcp auth --client-id YOUR_KEY --client-secret YOUR_SECRET

# If running from source
uv run schwab-mcp auth --client-id YOUR_KEY --client-secret YOUR_SECRET
```

This opens a browser, you log in to Schwab, and the token is automatically captured and saved to `~/.local/share/schwab-mcp/token.yaml`.

#### Manual Authentication (Copy/Paste)

Use `--manual` when your Developer Portal callback URL is **not** `https://127.0.0.1:8182` (e.g., you use a custom domain):

```bash
uv run schwab-mcp auth \
  --client-id YOUR_KEY \
  --client-secret YOUR_SECRET \
  --callback-url https://your-domain.com/callback \
  --manual
```

**Step-by-step process:**

1. The tool displays an authorization URL - copy it
2. Open the URL in any browser
3. Log in to Schwab with your credentials
4. Complete 2FA if prompted (text message, authenticator, etc.)
5. Click "Allow" when asked to grant the app access to your account
6. Your browser will redirect to your callback URL (e.g., `https://your-domain.com/callback?code=LONG_CODE`)
7. The page will show an error (domain not responding) - **this is expected**
8. **Copy the entire URL from your browser's address bar** (including the `?code=...` part)
9. Paste the URL into the terminal prompt and press Enter
10. Authentication complete! Token saved.

**When to use manual mode:**
- Your callback URL is a custom domain (not localhost)
- You can't change the callback URL immediately (requires market close)
- Browser security settings block the automatic flow
- Testing with different callback configurations

**Example manual session:**
```bash
$ uv run schwab-mcp auth --client-id ABC123... --manual
...
Redirect URL> https://your-domain.com/callback?code=ABC123XYZ...&state=...
✓ Authentication successful!
```

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

#### Browser Selection

If the default browser doesn't work (e.g., Chrome blocks self-signed certificates), specify a different browser:

```bash
uv run schwab-mcp auth --client-id YOUR_KEY --client-secret YOUR_SECRET --browser safari
# or --browser firefox
```

## Configuration

You can configure the server using CLI flags or Environment Variables.

### Authentication Options

| Flag | Env Variable | Description |
|------|--------------|-------------|
| `--client-id` | `SCHWAB_CLIENT_ID` | **Required**. Schwab App Key. |
| `--client-secret` | `SCHWAB_CLIENT_SECRET` | **Required**. Schwab App Secret. |
| `--callback-url` | `SCHWAB_CALLBACK_URL` | Redirect URL (default: `https://127.0.0.1:8182`). |
| `--manual` | N/A | Use manual auth (copy/paste callback URL). |
| `--browser` | N/A | Browser to use (e.g., `safari`, `firefox`). |
| `--token-path` | N/A | Path to save/load token (default: `~/.local/share/...`). |

### Server Options

| Flag | Env Variable | Description |
|------|--------------|-------------|
| `--jesus-take-the-wheel`| N/A | **DANGER**. Bypasses Discord approval for trades. |
| `--no-technical-tools` | N/A | Disables technical analysis tools (SMA, RSI, etc.). |
| `--json` | N/A | Returns raw JSON instead of formatted text (useful for some agents). |

### Database Options (Optional)

Enable automatic storage of option chain data to PostgreSQL/Cloud SQL:

| Flag | Env Variable | Description |
|------|--------------|-------------|
| `--db-instance` | `SCHWAB_DB_INSTANCE` | Cloud SQL connection name (`project:region:instance`). |
| `--db-name` | `SCHWAB_DB_NAME` | Database name (default: `schwab_data`). |
| `--db-user` | `SCHWAB_DB_USER` | Database username (default: `agent_user`). |
| `--db-password` | `SCHWAB_DB_PASSWORD` | Database password. |

**When database is enabled:**
- Option chain fetches automatically store full data
- Tools return compact summaries instead of 250KB+ responses
- Query stored data with filters: `query_stored_options(symbol='SPY', min_delta=0.40)`
- Compare options across time: `compare_option_snapshots()`

**Example with database:**
```bash
schwab-mcp server \
  --client-id YOUR_KEY \
  --client-secret YOUR_SECRET \
  --db-instance my-project:us-central1:my-db \
  --db-password DB_PASSWORD
```

Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable to authenticate to Cloud SQL.

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
