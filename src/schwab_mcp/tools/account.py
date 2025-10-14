#

from typing import Annotated

from mcp.server.fastmcp import Context

from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call, get_account_client


@register
async def get_account_numbers(
    ctx: Context,
) -> str:
    """
    Returns mapping of account IDs to account hashes. Hashes required for account-specific calls. Use first.
    """
    client = get_account_client(ctx)
    return await call(client.get_account_numbers)


@register
async def get_accounts(
    ctx: Context,
) -> str:
    """
    Returns balances/info for all linked accounts (funds, cash, margin). Does not return hashes; use get_account_numbers first.
    """
    client = get_account_client(ctx)
    return await call(client.get_accounts)


@register
async def get_accounts_with_positions(
    ctx: Context,
) -> str:
    """
    Returns balances, info, and positions (holdings, cost, gain/loss) for all linked accounts. Does not return hashes; use get_account_numbers first.
    """
    client = get_account_client(ctx)
    return await call(client.get_accounts, fields=[client.Account.Fields.POSITIONS])


@register
async def get_account(
    ctx: Context,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance/info for a specific account via account_hash (from get_account_numbers). Includes funds, cash, margin info.
    """
    client = get_account_client(ctx)
    return await call(client.get_account, account_hash)


@register
async def get_account_with_positions(
    ctx: Context,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance, info, and positions for a specific account via account_hash. Includes holdings, quantity, cost basis, unrealized gain/loss.
    """
    client = get_account_client(ctx)
    return await call(
        client.get_account, account_hash, fields=[client.Account.Fields.POSITIONS]
    )


@register
async def get_user_preferences(
    ctx: Context,
) -> str:
    """
    Returns user preferences (nicknames, display settings, notifications) for all linked accounts.
    """
    client = get_account_client(ctx)
    return await call(client.get_user_preferences)
