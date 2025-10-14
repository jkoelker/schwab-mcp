#

from typing import Annotated

import datetime
from mcp.server.fastmcp import FastMCP

from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.tools.utils import JSONType, call


async def get_transactions(
    ctx: SchwabContext,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_account_numbers)"
    ],
    start_date: Annotated[
        str | None,
        "Start date ('YYYY-MM-DD', max 60 days past, default 60 days ago)",
    ] = None,
    end_date: Annotated[str | None, "End date ('YYYY-MM-DD', default today)"] = None,
    transaction_type: Annotated[
        list[str] | str | None,
        "Filter by type(s) (list/str): TRADE, DIVIDEND_OR_INTEREST, ACH_RECEIPT, etc. Default all.",
    ] = None,
    symbol: Annotated[str | None, "Filter transactions by security symbol"] = None,
) -> JSONType:
    """
    Get transaction history (trades, deposits, dividends, etc.) for an account. Filter by date range (max 60 days past), type, symbol.
    Params: account_hash, start_date (YYYY-MM-DD), end_date (YYYY-MM-DD), transaction_type (list/str: TRADE/DIVIDEND_OR_INTEREST/etc.), symbol.
    Use tomorrow's date as end_date for today's transactions. See full type list in original docstring if needed.
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.transactions

    start_date_obj = None
    end_date_obj = None

    if start_date is not None:
        start_date_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()

    if end_date is not None:
        end_date_obj = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    transaction_type_enums = None
    if transaction_type is not None:
        if isinstance(transaction_type, str):
            transaction_type = [t.strip() for t in transaction_type.split(",")]
        transaction_type_enums = [
            client.Transaction.TransactionType[t.upper()] for t in transaction_type
        ]

    # Corrected function name to client.get_transactions and keyword arg to transaction_types
    return await call(
        client.get_transactions,
        account_hash,
        start_date=start_date_obj,
        end_date=end_date_obj,
        transaction_types=transaction_type_enums,  # Corrected keyword argument
        symbol=symbol,
    )


async def get_transaction(
    ctx: SchwabContext,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    transaction_id: Annotated[str, "Transaction ID (from get_transactions)"],
) -> JSONType:
    """
    Get detailed info for a specific transaction by ID.
    Params: account_hash, transaction_id (from get_transactions).
    """
    context: SchwabServerContext = ctx.request_context.lifespan_context
    client = context.transactions
    return await call(client.get_transaction, account_hash, transaction_id)


_READ_ONLY_TOOLS = (
    get_transactions,
    get_transaction,
)


def register(server: FastMCP, *, allow_write: bool) -> None:
    _ = allow_write
    for func in _READ_ONLY_TOOLS:
        register_tool(server, func)
