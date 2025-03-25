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
    Returns details for a specific order.

    Fetches comprehensive information about an order identified by order_id
    and account_hash. Returns full execution details, status, price, quantity,
    and other order-specific information.

    Parameters:
    - account_hash: Hash identifying the account (from get_account_numbers)
    - order_id: ID of the order to retrieve details for

    Use to examine the current state and execution details of a specific order.
    """
    return await call(client.get_order, order_id=order_id, account_hash=account_hash)


@register
async def get_orders(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[
        str, "Account hash for the Schwab account (from get_account_numbers)"
    ],
    max_results: Annotated[
        int | None, "Maximum number of orders to return (limit results)"
    ] = None,
    from_date: Annotated[
        str | None,
        "Start date for orders in 'YYYY-MM-DD' format (up to 60 days in past)",
    ] = None,
    to_date: Annotated[str | None, "End date for orders in 'YYYY-MM-DD' format"] = None,
    status: Annotated[
        list[str] | str | None, "Filter by specific order status (see options below)"
    ] = None,
) -> str:
    """
    Returns order history for a specific account.

    Retrieves orders with status, execution details, and specifications.
    Filter by date range and order status.

    Parameters:
    - account_hash: Hash identifying the account (from get_account_numbers)
    - max_results: Optional limit on number of orders to return
    - from_date: Start date in 'YYYY-MM-DD' format (up to 60 days in past)
    - to_date: End date in 'YYYY-MM-DD' format
    - status: Filter by specific order status, options:
      - AWAITING_PARENT_ORDER: Waiting for parent order conditions
      - AWAITING_CONDITION: Waiting for specified conditions
      - AWAITING_STOP_CONDITION: Waiting for stop price to trigger
      - AWAITING_MANUAL_REVIEW: Being reviewed by broker
      - ACCEPTED: Order accepted but not processed
      - AWAITING_UR_OUT: Waiting for broker response
      - PENDING_ACTIVATION: Ready to activate (e.g., at market open)
      - QUEUED: In queue for processing
      - WORKING: Order is active and working
      - REJECTED: Order was rejected
      - PENDING_CANCEL: Cancellation requested but not confirmed
      - CANCELED: Order successfully canceled
      - PENDING_REPLACE: Modification requested but not confirmed
      - REPLACED: Order successfully modified
      - FILLED: Order fully executed
      - EXPIRED: Order expired without full execution
      - NEW: New order being processed
      - AWAITING_RELEASE_TIME: Waiting for scheduled release time
      - PENDING_ACKNOWLEDGEMENT: Waiting for acknowledgement
      - PENDING_RECALL: Pending recall from execution venue

    Notes:
    - For today's orders, use tomorrow's date as to_date
    - Without status filter, returns all orders
    - Use WORKING to get all open orders if market is open
    - Use PENDING_ACTIVATION to get all open orders if market is closed
    """
    if from_date is not None:
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date is not None:
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()

    return await call(
        client.get_orders_for_account,
        account_hash,
        max_results=max_results,
        from_entered_datetime=from_date,
        to_entered_datetime=to_date,
        status=client.Order.Status[status] if status else None,
    )


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
