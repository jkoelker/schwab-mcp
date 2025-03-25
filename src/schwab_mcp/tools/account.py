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
    Returns a mapping from account IDs to account hashes.

    Account hashes must be used in all account-specific API calls for security.
    This is typically the first call needed before performing account operations.
    """
    return await call(client.get_account_numbers)


@register
async def get_accounts(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns account balances and information for all linked accounts.

    Includes available funds, cash balances, and margin information.
    Note: Does not return account hashes; use `get_account_numbers` first.
    """
    return await call(client.get_accounts)


@register
async def get_accounts_with_positions(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns account balances and current positions for all linked accounts.

    Includes holdings data with quantity, cost basis, and unrealized gain/loss.
    Note: Does not return account hashes; use `get_account_numbers` first.
    """
    return await call(client.get_accounts, fields=[client.Account.Fields.POSITIONS])


@register
async def get_account(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance and information for a specific account.

    Includes available funds, cash balances, and margin information for the account
    identified by account_hash (obtained from get_account_numbers).
    """
    return await call(client.get_account, account_hash)


@register
async def get_account_with_positions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance, information and positions for a specific account.

    Similar to get_account() but also includes position data (holdings, quantity,
    cost basis, unrealized gain/loss) for comprehensive portfolio analysis.
    """
    return await call(
        client.get_account, account_hash, fields=[client.Account.Fields.POSITIONS]
    )


@register
async def get_user_preferences(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns user preferences for all linked accounts.

    Includes account nicknames, display preferences, and notification settings
    that can be used for personalized UI presentation.
    """
    return await call(client.get_user_preferences)
