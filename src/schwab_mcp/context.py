from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from schwab.client import AsyncClient
from mcp.server.fastmcp import Context as MCPContext

from schwab_mcp.approvals import ApprovalManager

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
    approval_manager: ApprovalManager
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


class SchwabContext(MCPContext[Any, SchwabServerContext, Any]):
    """FastMCP context with typed accessors for Schwab APIs."""

    @property
    def schwab(self) -> SchwabServerContext:
        context = self.request_context.lifespan_context
        if context is None:
            raise RuntimeError("Schwab context is unavailable outside a request")
        return context

    @property
    def client(self) -> AsyncClient:
        return self.schwab.client

    @property
    def approvals(self) -> ApprovalManager:
        return self.schwab.approval_manager

    @property
    def tools(self) -> ToolsClient:
        return self.schwab.tools

    @property
    def accounts(self) -> AccountClient:
        return self.schwab.accounts

    @property
    def price_history(self) -> PriceHistoryClient:
        return self.schwab.price_history

    @property
    def options(self) -> OptionsClient:
        return self.schwab.options

    @property
    def orders(self) -> OrdersClient:
        return self.schwab.orders

    @property
    def quotes(self) -> QuotesClient:
        return self.schwab.quotes

    @property
    def transactions(self) -> TransactionsClient:
        return self.schwab.transactions


__all__ = ["SchwabServerContext", "SchwabContext"]
