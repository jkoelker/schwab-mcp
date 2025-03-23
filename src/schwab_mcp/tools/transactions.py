#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_transactions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    start_date: Annotated[str | None, "Start date for transactions"] = None,
    end_date: Annotated[str | None, "End date for transactions"] = None,
    transaction_type: Annotated[list[str] | str | None, "Transaction type to filter by"] = None,
    symbol: Annotated[str | None, "Symbol to filter by"] = None,
) -> str:
    """
    Get transactions for a specific Schwab account.

    start_date and end_date should be in the format 'YYYY-MM-DD'.
    start_date can be up to 60 days in the past.
    If you want to see today's transactions, pass tomorrow's date as the 'end_date'.

    transaction_type can be one of the following:
      TRADE
      RECEIVE_AND_DELIVER
      DIVIDEND_OR_INTEREST
      ACH_RECEIPT
      ACH_DISBURSEMENT
      CASH_RECEIPT
      CASH_DISBURSEMENT
      ELECTRONIC_FUND
      WIRE_OUT
      WIRE_IN
      JOURNAL
      MEMORANDUM
      MARGIN_CALL
      MONEY_MARKET
      SMA_ADJUSTMENT

    If transaction_type is not provided, all transactions will be returned.

    If symbol is provided, only transactions for that symbol will be returned.
    """
    if start_date is not None:
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()

    if end_date is not None:
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    if transaction_type is not None:
        if isinstance(transaction_type, str):
            transaction_type = [transaction_type]
        transaction_type = [client.Transaction.TransactionType[t] for t in transaction_type]

    return await call(
        client.get_transactions_for_account,
        account_hash,
        start_date=start_date,
        end_date=end_date,
        transaction_type=transaction_type,
        symbol=symbol,
    )


@register
async def get_transaction(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    transaction_id: Annotated[str, "Transaction ID to get details for"],
) -> str:
    """Get details for a specific transaction"""
    return await call(client.get_transaction, account_hash, transaction_id)
