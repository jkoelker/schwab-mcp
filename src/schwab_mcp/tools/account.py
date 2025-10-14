#

from typing import Annotated

from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_account_numbers(
    ctx: SchwabContext,
) -> str:
    """
    Returns mapping of account IDs to account hashes. Hashes required for account-specific calls. Use first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_account_numbers)


@register
async def get_accounts(
    ctx: SchwabContext,
) -> str:
    """
    Returns balances/info for all linked accounts (funds, cash, margin). Does not return hashes; use get_account_numbers first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_accounts)


@register
async def get_accounts_with_positions(
    ctx: SchwabContext,
) -> str:
    """
    Returns balances, info, and positions (holdings, cost, gain/loss) for all linked accounts. Does not return hashes; use get_account_numbers first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(
        context.accounts.get_accounts,
        fields=[context.accounts.Account.Fields.POSITIONS],
    )


@register
async def get_account(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance/info for a specific account via account_hash (from get_account_numbers). Includes funds, cash, margin info.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_account, account_hash)


@register
async def get_account_with_positions(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> str:
    """
    Returns balance, info, and positions for a specific account via account_hash. Includes holdings, quantity, cost basis, unrealized gain/loss.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(
        context.accounts.get_account,
        account_hash,
        fields=[context.accounts.Account.Fields.POSITIONS],
    )


@register
async def get_user_preferences(
    ctx: SchwabContext,
) -> str:
    """
    Returns user preferences (nicknames, display settings, notifications) for all linked accounts.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_user_preferences)
