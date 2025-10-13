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
    Returns mapping of account IDs to account hashes. Hashes required for account-specific calls. Use first.
    """
    return await call(client.get_account_numbers)


@register
async def get_accounts(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns balances/info for all linked accounts (funds, cash, margin). Does not return hashes; use get_account_numbers first.
    """
    return await call(client.get_accounts)


@register
async def get_accounts_with_positions(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns balances, info, and positions (holdings, cost, gain/loss) for all linked accounts. Does not return hashes; use get_account_numbers first.
    """
    return await call(client.get_accounts, fields=[client.Account.Fields.POSITIONS])


@register
async def get_account(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance/info for a specific account via account_hash (from get_account_numbers). Includes funds, cash, margin info.
    """
    return await call(client.get_account, account_hash)


@register
async def get_account_with_positions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance, info, and positions for a specific account via account_hash. Includes holdings, quantity, cost basis, unrealized gain/loss.
    """
    return await call(
        client.get_account, account_hash, fields=[client.Account.Fields.POSITIONS]
    )


@register
async def get_user_preferences(
    client: schwab.client.AsyncClient,
) -> str:
    """
    Returns user preferences (nicknames, display settings, notifications) for all linked accounts.
    """
    return await call(client.get_user_preferences)
