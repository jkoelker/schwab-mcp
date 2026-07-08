#

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call

_COMPACT_ACCOUNT_FIELDS = frozenset(
    {"type", "accountNumber", "roundTrips", "isDayTrader"}
)

_COMPACT_BALANCE_FIELDS = frozenset(
    {
        "equity",
        "buyingPower",
        "cashBalance",
        "cashAvailableForTrading",
        "liquidationValue",
    }
)


def _prune_position(position: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    instrument = position.get("instrument")
    if isinstance(instrument, dict):
        symbol = instrument.get("symbol")
        if symbol is not None:
            result["symbol"] = symbol
    # Net quantity: positive = long, negative = short
    long_qty = position.get("longQuantity", 0)
    short_qty = position.get("shortQuantity", 0)
    if not isinstance(long_qty, (int, float)):
        long_qty = 0
    if not isinstance(short_qty, (int, float)):
        short_qty = 0
    result["quantity"] = long_qty - short_qty
    market_value = position.get("marketValue")
    if market_value is not None:
        result["marketValue"] = market_value
    average_price = position.get("averagePrice")
    if average_price is not None:
        result["averagePrice"] = average_price
    unrealized_pl = position.get("currentDayProfitLoss")
    if unrealized_pl is not None:
        result["unrealizedPL"] = unrealized_pl
    return result


def _prune_securities_account(sec_account: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        k: v for k, v in sec_account.items() if k in _COMPACT_ACCOUNT_FIELDS
    }
    current_balances = sec_account.get("currentBalances")
    if not isinstance(current_balances, dict):
        current_balances = {}
    result["currentBalances"] = {
        k: v for k, v in current_balances.items() if k in _COMPACT_BALANCE_FIELDS
    }
    if "positions" in sec_account:
        positions = sec_account["positions"]
        if isinstance(positions, list):
            result["positions"] = [_prune_position(p) for p in positions]
        else:
            result["positions"] = positions
    return result


def _prune_account_response(payload: JSONType) -> JSONType:
    if isinstance(payload, list):
        return [
            {"securitiesAccount": _prune_securities_account(item["securitiesAccount"])}
            if isinstance(item, dict)
            and "securitiesAccount" in item
            and isinstance(item["securitiesAccount"], dict)
            else item
            for item in payload
        ]
    if isinstance(payload, dict) and "securitiesAccount" in payload:
        sec = payload["securitiesAccount"]
        if isinstance(sec, dict):
            return {"securitiesAccount": _prune_securities_account(sec)}
        return payload
    return payload


async def get_account_numbers(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns mapping of account IDs to account hashes. Hashes required for account-specific calls. Use first.
    """
    return await call(ctx.accounts.get_account_numbers)


async def get_accounts(
    ctx: SchwabContext,
    include_positions: Annotated[
        bool,
        "Include holdings/positions (symbol, quantity, marketValue, averagePrice, unrealizedPL) for each account.",
    ] = False,
    verbose: Annotated[
        bool,
        "Return the full raw payload (all balance types, full position fields) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns balances/info for all linked accounts (funds, cash, margin); pass include_positions=True to also include holdings. Does not return hashes; use get_account_numbers first.
    By default returns compact fields only (account type/number, equity/buyingPower/cashBalance/cashAvailableForTrading/liquidationValue from currentBalances; initialBalances and projectedBalances are dropped; positions if included are reduced to symbol, net quantity (positive=long/negative=short), marketValue, averagePrice, unrealizedPL); pass verbose=True for the full raw payload.
    """
    kwargs: dict[str, Any] = {}
    if include_positions:
        kwargs["fields"] = [ctx.accounts.Account.Fields.POSITIONS]
    result = await call(ctx.accounts.get_accounts, **kwargs)
    return result if verbose else _prune_account_response(result)


async def get_account(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    include_positions: Annotated[
        bool,
        "Include holdings/positions (symbol, quantity, marketValue, averagePrice, unrealizedPL).",
    ] = False,
    verbose: Annotated[
        bool,
        "Return the full raw payload (all balance types, full position fields) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns balance/info for a specific account via account_hash (from get_account_numbers); pass include_positions=True to also include holdings. Includes funds, cash, margin info.
    By default returns compact fields only (account type/number, equity/buyingPower/cashBalance/cashAvailableForTrading/liquidationValue from currentBalances; initialBalances and projectedBalances are dropped; positions if included are reduced to symbol, net quantity (positive=long/negative=short), marketValue, averagePrice, unrealizedPL); pass verbose=True for the full raw payload.
    """
    kwargs: dict[str, Any] = {}
    if include_positions:
        kwargs["fields"] = [ctx.accounts.Account.Fields.POSITIONS]
    result = await call(ctx.accounts.get_account, account_hash, **kwargs)
    return result if verbose else _prune_account_response(result)


async def get_user_preferences(
    ctx: SchwabContext,
) -> JSONType:
    """
    Returns user preferences (nicknames, display settings, notifications) for all linked accounts.
    """
    return await call(ctx.accounts.get_user_preferences)


_READ_ONLY_TOOLS = (
    get_account_numbers,
    get_accounts,
    get_account,
    get_user_preferences,
)


def register(
    server: FastMCP,
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func, result_transform=result_transform)
