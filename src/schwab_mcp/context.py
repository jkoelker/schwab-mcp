from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from schwab.client import AsyncClient
from mcp.server.fastmcp import Context as MCPContext

if TYPE_CHECKING:
    from schwab_mcp.tools._protocols import (
        AccountClient,
        OptionsClient,
        OrdersClient,
        PriceHistoryClient,
        QuotesClient,
        ToolsClient,
        TransactionsClient,
    )
else:  # pragma: no cover - runtime only
    AccountClient = OptionsClient = OrdersClient = PriceHistoryClient = QuotesClient = (
        ToolsClient
    ) = TransactionsClient = Any


@dataclass(slots=True)
class SchwabServerContext:
    """Typed application context shared via FastMCP lifespan."""

    client: AsyncClient
    tools: ToolsClient = field(init=False)
    accounts: AccountClient = field(init=False)
    price_history: PriceHistoryClient = field(init=False)
    options: OptionsClient = field(init=False)
    orders: OrdersClient = field(init=False)
    quotes: QuotesClient = field(init=False)
    transactions: TransactionsClient = field(init=False)

    def __post_init__(self) -> None:
        self.tools = cast(ToolsClient, self.client)
        self.accounts = cast(AccountClient, self.client)
        self.price_history = cast(PriceHistoryClient, self.client)
        self.options = cast(OptionsClient, self.client)
        self.orders = cast(OrdersClient, self.client)
        self.quotes = cast(QuotesClient, self.client)
        self.transactions = cast(TransactionsClient, self.client)


SchwabContext = MCPContext[Any, SchwabServerContext, Any]


__all__ = ["SchwabServerContext", "SchwabContext"]
