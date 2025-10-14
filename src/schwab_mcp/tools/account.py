#

from typing import Annotated

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call


async def get_account_numbers(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns mapping of account IDs to account hashes. Hashes required for account-specific calls. Use first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_account_numbers)


async def get_accounts(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns balances/info for all linked accounts (funds, cash, margin). Does not return hashes; use get_account_numbers first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_accounts)


async def get_accounts_with_positions(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns balances, info, and positions (holdings, cost, gain/loss) for all linked accounts. Does not return hashes; use get_account_numbers first.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(
        context.accounts.get_accounts,
        fields=[context.accounts.Account.Fields.POSITIONS],
    )


async def get_account(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> JSONType:
    """
    Returns balance/info for a specific account via account_hash (from get_account_numbers). Includes funds, cash, margin info.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_account, account_hash)


async def get_account_with_positions(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
) -> JSONType:
    """
    Returns balance, info, and positions for a specific account via account_hash. Includes holdings, quantity, cost basis, unrealized gain/loss.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(
        context.accounts.get_account,
        account_hash,
        fields=[context.accounts.Account.Fields.POSITIONS],
    )


async def get_user_preferences(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns user preferences (nicknames, display settings, notifications) for all linked accounts.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    return await call(context.accounts.get_user_preferences)


_READ_ONLY_TOOLS = (
    get_account_numbers,
    get_accounts,
    get_accounts_with_positions,
    get_account,
    get_account_with_positions,
    get_user_preferences,
)


def register(server: FastMCP, *, allow_write: bool) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func)
