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
    """Get details for a specific order"""
    return await call(client.get_order, order_id=order_id, account_hash=account_hash)


@register
async def get_orders(
    client: schwab.client.AsyncClient,
    account_hash: Annotated[str, "Account hash for the Schwab account"],
    max_results: Annotated[int | None, "Maximum number of orders to return"] = None,
    from_date: Annotated[str | None, "Start date for orders"] = None,
    to_date: Annotated[str | None, "End date for orders"] = None,
    status: Annotated[list[str] | str | None, "Order status to filter by"] = None,
) -> str:
    """
    Get orders for a specific Schwab account.

    From and to dates should be in the format 'YYYY-MM-DD'.
    From date can be up to 60 days in the past.
    If you want to see today's orders, pass tomorrow's date as the 'to_date'.

    Status can be one of the following:
      AWAITING_PARENT_ORDER
      AWAITING_CONDITION
      AWAITING_STOP_CONDITION
      AWAITING_MANUAL_REVIEW
      ACCEPTED
      AWAITING_UR_OUT
      PENDING_ACTIVATION
      QUEUED
      WORKING
      REJECTED
      PENDING_CANCEL
      CANCELED
      PENDING_REPLACE
      REPLACED
      FILLED
      EXPIRED
      NEW
      AWAITING_RELEASE_TIME
      PENDING_ACKNOWLEDGEMENT
      PENDING_RECALL

    If status is not provided, all orders will be returned.
    To get all open orders if the market is open send status='WORKING'.
    To get all open orders if the market is closed send status='PENDING_ACTIVATION'.
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
    """Cancel a specific order"""
    return await call(client.cancel_order, order_id=order_id, account_hash=account_hash)
