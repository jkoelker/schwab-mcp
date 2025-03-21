#

from typing import Annotated, Callable

import schwab.client
from schwab_mcp.tools.registry import register


async def call(func: Callable, *args, **kwargs):
    """Call a method on the Schwab client"""
    response = await func(*args, **kwargs)
    response.raise_for_status()
    return response.text


@register
async def get_account_numbers(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns a mapping from account IDs available to this token to the
    account hash that should be passed whenever referring to that account in
    API calls."""
    return await call(client.get_account_numbers)

@register
async def get_accounts(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Account balances and information for all linked accounts. Note this
    method does not return account hashes, call `get_account_numbers`
    to get the mapping from account IDs to account hashes.
    """
    return await call(client.get_accounts)

@register
async def get_accounts_with_positions(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Account balances and information for all linked accounts, including
    positions. Note this method does not return account hashes, call
    `get_account_numbers` to get the mapping from account IDs to account hashes.
    """
    return await call(client.get_accounts, fields=[client.Account.Fields.POSITIONS])

@register
async def get_account(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """Get account balance and information for a specific Schwab account"""
    return await call(client.get_account, account_hash)

@register
async def get_account_with_positions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Get account balance and information for a specific Schwab account,
    including positions
    """
    return await call(client.get_account, account_hash, fields=[client.Account.Fields.POSITIONS])

@register
async def get_user_preferences(
    client: schwab.client.AsyncClient,
) -> str:
    """Get user preferences for all accounts including the account nicknames"""
    return await call(client.get_user_preferences)


@register
async def get_quotes(
    client: schwab.client.AsyncClient,
    symbols: Annotated[list[str] | str, "List of stock symbols to get quotes for"],
) -> str:
    """Get quotes for specified symbols"""
    # Handle string input for backward compatibility
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]

    return await call(client.get_quotes, symbols)


@register
async def get_orders(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """Get orders for a specific Schwab account"""
    return await call(client.get_orders, account_hash)


@register
async def get_transactions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """Get transactions for a specific Schwab account"""
    return await call(client.get_transactions, account_hash)
