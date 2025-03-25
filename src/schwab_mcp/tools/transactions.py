#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_transactions(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_account_numbers)"
    ],
    start_date: Annotated[
        str | None,
        "Start date for transactions in 'YYYY-MM-DD' format (up to 60 days in past)",
    ] = None,
    end_date: Annotated[
        str | None, "End date for transactions in 'YYYY-MM-DD' format"
    ] = None,
    transaction_type: Annotated[
        list[str] | str | None,
        "Filter by specific transaction types (see options below)",
    ] = None,
    symbol: Annotated[str | None, "Filter transactions by security symbol"] = None,
) -> str:
    """
    Get transaction history for a specific Schwab account.

    This function retrieves the transaction history for an account, including trades,
    deposits, withdrawals, dividend payments, and other financial activities. Results
    can be filtered by date range, transaction type, and security symbol. The data
    returned includes transaction dates, types, amounts, descriptions, and transaction IDs
    which can be used with get_transaction() to fetch more detailed information.

    This comprehensive transaction history is useful for account reconciliation,
    tax preparation, performance analysis, and monitoring account activity.

    Important date restrictions:
    - start_date and end_date should be in the format 'YYYY-MM-DD'
    - start_date can be up to 60 days in the past
    - If not specified, start_date defaults to 60 days ago
    - If not specified, end_date defaults to current date
    - To see today's transactions, use tomorrow's date as the 'end_date'

    transaction_type can be one of the following:
      TRADE - Security buy/sell transactions
      RECEIVE_AND_DELIVER - Securities transfers in/out
      DIVIDEND_OR_INTEREST - Dividend and interest payments
      ACH_RECEIPT - Electronic deposits
      ACH_DISBURSEMENT - Electronic withdrawals
      CASH_RECEIPT - Cash deposits
      CASH_DISBURSEMENT - Cash withdrawals
      ELECTRONIC_FUND - Electronic fund transfers
      WIRE_OUT - Wire transfers out
      WIRE_IN - Wire transfers in
      JOURNAL - Journal entries
      MEMORANDUM - Memo entries
      MARGIN_CALL - Margin call activities
      MONEY_MARKET - Money market transactions
      SMA_ADJUSTMENT - Special Memorandum Account adjustments

    If transaction_type is not provided, all transaction types will be returned.
    If symbol is provided, only transactions for that specific security will be returned.
    """
    if start_date is not None:
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()

    if end_date is not None:
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    if transaction_type is not None:
        if isinstance(transaction_type, str):
            transaction_type = [transaction_type]
        transaction_type = [
            client.Transaction.TransactionType[t] for t in transaction_type
        ]

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
    """
    Get detailed information for a specific transaction by ID.

    This function retrieves comprehensive details about a single transaction identified
    by its transaction ID for a specific account. The response includes complete information
    about the transaction such as type, date, amount, description, fees, settlement date,
    and other transaction-specific details.

    Use this function when you need to examine the full details of a particular transaction
    after discovering its ID through the get_transactions function. This is useful for
    transaction reconciliation, record-keeping, or investigating specific account activities.
    """
    return await call(client.get_transaction, account_hash, transaction_id)
