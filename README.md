# Schwab Model Context Protocol Server

This is a server that implements the Model Context Protocol (MCP) for
the Schwab API using [schwab-py](https://github.com/alexgolec/schwab-py) and
the MCP [python-sdk](https://github.com/modelcontextprotocol/python-sdk).

## Features

- Expose Schwab API functionality through Model Context Protocol
- Get account information and positions
- Retrieve stock quotes
- Get order and transaction history
- Designed to integrate with Large Language Models (LLMs)

## Installation

```bash
# Install with all dependencies
uv add -e .

# Install development dependencies
uv add -e .[dev]
```

## Usage

### Authentication

The first step is to authenticate with the Schwab API and generate a token:

```bash
# Authenticate and generate a token
uv run schwab-mcp auth --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --callback-url YOUR_CALLBACK_URL
```

You can set these credentials through environment variables to avoid typing them each time:
- `SCHWAB_CLIENT_ID`
- `SCHWAB_CLIENT_SECRET`
- `SCHWAB_CALLBACK_URL` (defaults to https://127.0.0.1:8182)

By default, the token is saved to `~/.local/share/schwab-mcp/token.yaml` (platform-specific). You can specify a different path:

```bash
uv run schwab-mcp auth --token-path /path/to/token.yaml
```

Both yaml and json token formats are supported and will be inferred from the file extension.

### Running the Server

After authentication, you can run the server:

```bash
# Run the server with default token path
uv run schwab-mcp server --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --callback-url YOUR_CALLBACK_URL

# Run with a custom token path
uv run schwab-mcp server --token-path /path/to/token.json --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --callback-url YOUR_CALLBACK_URL
```

Token age is validated - if older than 5 days, you will be prompted to re-authenticate.

## Available Tools

The server exposes the following MCP tools:

### Date and Market Information
1. `get_datetime` - Get the current datetime in ISO format
2. `get_market_hours` - Get market hours for a specific market
3. `get_movers` - Get movers for a specific index

### Account Information
4. `get_account_numbers` - Get mapping of account IDs to account hashes
5. `get_accounts` - Get information for all linked Schwab accounts
6. `get_accounts_with_positions` - Get accounts with position information
7. `get_account` - Get information for a specific account
8. `get_account_with_positions` - Get specific account with position information
9. `get_user_preferences` - Get user preferences for all accounts including nicknames

### Orders
10. `get_order` - Get details for a specific order
11. `get_orders` - Get orders for a specific account

### Quotes
12. `get_quotes` - Get quotes for specified symbols

### Transactions
13. `get_transactions` - Get transactions for a specific account
14. `get_transaction` - Get details for a specific transaction

## Development

```bash
# Type check
uv run pyright

# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Run tests
uv run pytest
```

## License

This project is available under the MIT License.
