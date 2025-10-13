#

from typing import Annotated

import datetime
import schwab.client
from schwab_mcp.tools.registry import register
from schwab_mcp.tools.utils import call


@register
async def get_order(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to get details for"],
) -> str:
    """
    Returns details for a specific order (ID, status, price, quantity, execution details). Params: account_hash, order_id.
    """
    return await call(client.get_order, order_id=order_id, account_hash=account_hash)


@register
async def get_orders(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_account_numbers)"
    ],
    max_results: Annotated[
        int | None, "Maximum number of orders to return"
    ] = None,
    from_date: Annotated[
        str | None,
        "Start date for orders ('YYYY-MM-DD', max 60 days past)",
    ] = None,
    to_date: Annotated[str | None, "End date for orders ('YYYY-MM-DD')"] = None,
    status: Annotated[
        list[str] | str | None, "Filter by order status (e.g., WORKING, FILLED, CANCELED). See full list below."
    ] = None,
) -> str:
    """
    Returns order history for an account. Filter by date range (max 60 days past) and status.
    Params: account_hash, max_results, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD), status (list/str).
    Status options: AWAITING_PARENT_ORDER, AWAITING_CONDITION, AWAITING_STOP_CONDITION, AWAITING_MANUAL_REVIEW, ACCEPTED, AWAITING_UR_OUT, PENDING_ACTIVATION, QUEUED, WORKING, REJECTED, PENDING_CANCEL, CANCELED, PENDING_REPLACE, REPLACED, FILLED, EXPIRED, NEW, AWAITING_RELEASE_TIME, PENDING_ACKNOWLEDGEMENT, PENDING_RECALL.
    Use tomorrow's date as to_date for today's orders. Use WORKING/PENDING_ACTIVATION for open orders.
    """
    from_date_obj = None
    to_date_obj = None

    if from_date is not None:
        from_date_obj = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date_obj = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

@register(write=True)
async def cancel_order(
    client: schwab.client.AsyncClient

@register(write=True)
async def cancel_order(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    order_id: Annotated[str, "Order ID to cancel"],
) -> str:
    """
    Cancels a pending order.

    Sends a cancellation request for an order that hasn't been executed yet.
    Orders that have already been executed (FILLED) or are in certain terminal
    states cannot be canceled.

    Parameters:
    - account_hash: Hash identifying the account (from get_account_numbers)
    - order_id: ID of the order to cancel

    Returns confirmation of cancellation request. The actual cancellation
    process may be asynchronous, so check order status after calling this
    function to confirm final cancellation state.

    Note: This is a write operation that will modify your account state.
    """
    return await call(client.cancel_order, order_id=order_id, account_hash=account_hash)
