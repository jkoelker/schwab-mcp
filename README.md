# Schwab Model Context Protocol Server

This is a server that implements the Model Context Protocol (MCP) for
the Schwab API using [schwab-py](https://github.com/alexgolec/schwab-py) and
the MCP [python-sdk](https://github.com/modelcontextprotocol/python-sdk).

## Features

- Expose Schwab API functionality through Model Context Protocol
- Get account information and positions
- Retrieve stock quotes and price history
- Get market information and movers
- Fetch option chains and expiration data
- Access order and transaction history
- Modify account state with special tools (requires `--jesus-take-the-wheel` flag)
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

# Run with account modification tools enabled
uv run schwab-mcp server --jesus-take-the-wheel --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --callback-url YOUR_CALLBACK_URL
```

Token age is validated - if older than 5 days, you will be prompted to re-authenticate.

> **WARNING**: Using the `--jesus-take-the-wheel` flag enables tools that can modify your account state. Use with caution as this allows LLMs to cancel orders and potentially perform other actions that change account state.

## Available Tools

The server exposes the following MCP tools:

### Date and Market Information
1. `get_datetime` - Get the current datetime in ISO format
2. `get_market_hours` - Get market hours for a specific market
3. `get_movers` - Get movers for a specific index
4. `get_instruments` - Search for instruments with a specific symbol

### Account Information
5. `get_account_numbers` - Get mapping of account IDs to account hashes
6. `get_accounts` - Get information for all linked Schwab accounts
7. `get_accounts_with_positions` - Get accounts with position information
8. `get_account` - Get information for a specific account
9. `get_account_with_positions` - Get specific account with position information
10. `get_user_preferences` - Get user preferences for all accounts including nicknames

### Orders
11. `get_order` - Get details for a specific order
12. `get_orders` - Get orders for a specific account

### Quotes
13. `get_quotes` - Get quotes for specified symbols

### Price History
14. `get_advanced_price_history` - Get advanced price history for a specific symbol
15. `get_price_history_every_minute` - Get price history with minute frequency
16. `get_price_history_every_five_minutes` - Get price history with five minute frequency
17. `get_price_history_every_ten_minutes` - Get price history with ten minute frequency
18. `get_price_history_every_fifteen_minutes` - Get price history with fifteen minute frequency
19. `get_price_history_every_thirty_minutes` - Get price history with thirty minute frequency
20. `get_price_history_every_day` - Get price history with daily frequency
21. `get_price_history_every_week` - Get price history with weekly frequency

### Options
22. `get_option_chain` - Get option chain for a specific symbol
23. `get_advanced_option_chain` - Get advanced option chain for a specific symbol
24. `get_option_expiration_chain` - Get option expiration information for a symbol

### Transactions
25. `get_transactions` - Get transactions for a specific account
26. `get_transaction` - Get details for a specific transaction

### Account Modification Tools (Requires `--jesus-take-the-wheel` flag)
27. `cancel_order` - Cancel a specific order

## Security Warning

The `--jesus-take-the-wheel` flag enables LLMs to perform actions that can modify your account state, including:
- Canceling orders
- Other actions that may have financial implications (more tools to be added in future releases)

Only use this flag in controlled environments and understand the risks involved.

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
