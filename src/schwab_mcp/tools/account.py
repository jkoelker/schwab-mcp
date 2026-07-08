#

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, SchwabAPIError, call

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


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    account_hash: str
    nickname: str | None
    is_default: bool


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


async def _get_identity_map(ctx: SchwabContext) -> dict[str, AccountIdentity]:
    """Build accountNumber -> AccountIdentity from account numbers and user preferences.

    Identity enrichment is best-effort metadata: if either upstream endpoint
    fails, callers still get their primary account/balance data, just without
    accountHash/nickname/isDefault enrichment (an empty map is returned).
    """
    try:
        numbers_payload = await call(ctx.accounts.get_account_numbers)
        prefs_payload = await call(ctx.accounts.get_user_preferences)
    except SchwabAPIError:
        return {}

    hash_map = {
        entry["accountNumber"]: entry["hashValue"]
        for entry in (numbers_payload if isinstance(numbers_payload, list) else [])
        if isinstance(entry, dict)
        and isinstance(entry.get("accountNumber"), str)
        and isinstance(entry.get("hashValue"), str)
    }

    accounts = (
        prefs_payload.get("accounts") if isinstance(prefs_payload, dict) else None
    )
    nick_map: dict[str, str | None] = {}
    default_map: dict[str, bool] = {}
    for acct in accounts if isinstance(accounts, list) else []:
        if not isinstance(acct, dict):
            continue
        acct_num = acct.get("accountNumber")
        if not isinstance(acct_num, str):
            continue
        nick_map[acct_num] = (
            acct.get("nickName") if isinstance(acct.get("nickName"), str) else None
        )
        default_map[acct_num] = acct.get("primaryAccount") is True

    return {
        acct_num: AccountIdentity(
            account_hash=hash_val,
            nickname=nick_map.get(acct_num),
            is_default=default_map.get(acct_num, False),
        )
        for acct_num, hash_val in hash_map.items()
    }


def _enrich_with_identity(
    payload: JSONType,
    identity_map: dict[str, AccountIdentity],
    *,
    fallback_hash: str | None = None,
) -> JSONType:
    """Inject accountHash, nickname, and isDefault into each securitiesAccount dict.

    Handles both list-of-accounts and single-account dict shapes.
    Always sets all three keys; falls back to fallback_hash (typically the
    account_hash the caller already supplied) if no identity-map entry is
    found, and uses None for nickname and False for isDefault in that case.
    """

    def _enrich_sec(sec: dict[str, Any]) -> None:
        acct_num = sec.get("accountNumber")
        identity = identity_map.get(acct_num) if isinstance(acct_num, str) else None
        sec["accountHash"] = identity.account_hash if identity else fallback_hash
        sec["nickname"] = identity.nickname if identity else None
        sec["isDefault"] = identity.is_default if identity else False

    if isinstance(payload, list):
        for item in payload:
            if (
                isinstance(item, dict)
                and "securitiesAccount" in item
                and isinstance(item["securitiesAccount"], dict)
            ):
                _enrich_sec(item["securitiesAccount"])
        return payload
    if isinstance(payload, dict) and "securitiesAccount" in payload:
        sec = payload["securitiesAccount"]
        if isinstance(sec, dict):
            _enrich_sec(sec)
    return payload


async def get_accounts(
    ctx: SchwabContext,
    include_positions: Annotated[
        bool,
        "Request holdings/positions for each account. In compact mode (default) positions are pruned to symbol, quantity, marketValue, averagePrice, unrealizedPL; verbose=True returns the raw, unpruned position fields instead.",
    ] = False,
    verbose: Annotated[
        bool,
        "Return the full raw payload (all balance types, and full position fields if include_positions=True) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns balances/info for all linked accounts (funds, cash, margin); pass include_positions=True to also include holdings.
    Includes each account's accountHash (required for account-specific calls like get_account, orders, transactions), nickname, and isDefault (the account marked as primary in Schwab user preferences).
    By default returns compact fields only (account type/number, equity/buyingPower/cashBalance/cashAvailableForTrading/liquidationValue from currentBalances; initialBalances and projectedBalances are dropped; positions if included are reduced to symbol, net quantity (positive=long/negative=short), marketValue, averagePrice, unrealizedPL); pass verbose=True for the full raw payload (positions unpruned if include_positions=True).
    """
    identity_map = await _get_identity_map(ctx)
    kwargs: dict[str, Any] = {}
    if include_positions:
        kwargs["fields"] = [ctx.accounts.Account.Fields.POSITIONS]
    result = await call(ctx.accounts.get_accounts, **kwargs)
    pruned = result if verbose else _prune_account_response(result)
    return _enrich_with_identity(pruned, identity_map)


async def get_account(
    ctx: SchwabContext,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_accounts)"
    ],
    include_positions: Annotated[
        bool,
        "Request holdings/positions. In compact mode (default) positions are pruned to symbol, quantity, marketValue, averagePrice, unrealizedPL; verbose=True returns the raw, unpruned position fields instead.",
    ] = False,
    verbose: Annotated[
        bool,
        "Return the full raw payload (all balance types, and full position fields if include_positions=True) instead of the compact default.",
    ] = False,
) -> JSONType:
    """
    Returns balance/info for a specific account via account_hash (from get_accounts); pass include_positions=True to also include holdings. Includes funds, cash, margin info.
    Includes the account's accountHash, nickname, and isDefault for self-describing output.
    By default returns compact fields only (account type/number, equity/buyingPower/cashBalance/cashAvailableForTrading/liquidationValue from currentBalances; initialBalances and projectedBalances are dropped; positions if included are reduced to symbol, net quantity (positive=long/negative=short), marketValue, averagePrice, unrealizedPL); pass verbose=True for the full raw payload (positions unpruned if include_positions=True).
    """
    identity_map = await _get_identity_map(ctx)
    kwargs: dict[str, Any] = {}
    if include_positions:
        kwargs["fields"] = [ctx.accounts.Account.Fields.POSITIONS]
    result = await call(ctx.accounts.get_account, account_hash, **kwargs)
    pruned = result if verbose else _prune_account_response(result)
    return _enrich_with_identity(pruned, identity_map, fallback_hash=account_hash)


_READ_ONLY_TOOLS = (
    get_accounts,
    get_account,
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
