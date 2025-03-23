#

from typing import Annotated

import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


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
    return await call(
        client.get_account, account_hash, fields=[client.Account.Fields.POSITIONS]
    )


@register
async def get_user_preferences(
    client: schwab.client.AsyncClient,
) -> str:
    """Get user preferences for all accounts including the account nicknames"""
    return await call(client.get_user_preferences)
