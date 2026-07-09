"""FastMCP context types that expose the Schwab client and supporting services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from mcp.server.fastmcp import Context as MCPContext
from schwab.client import AsyncClient

from schwab_mcp.approvals import ApprovalManager
from schwab_mcp.previews import PreviewStore

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
    AccountClient = OptionsClient = OrdersClient = PriceHistoryClient = QuotesClient = ToolsClient = (
        TransactionsClient
    ) = Any


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
    preview_store: PreviewStore = field(default_factory=PreviewStore)

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
        """Return the lifespan-scoped server context."""
        context = self.request_context.lifespan_context
        if context is None:
            raise RuntimeError("Schwab context is unavailable outside a request")
        return context

    @property
    def client(self) -> AsyncClient:
        """Return the raw Schwab async client."""
        return self.schwab.client

    @property
    def approvals(self) -> ApprovalManager:
        """Return the active approval manager."""
        return self.schwab.approval_manager

    @property
    def previews(self) -> PreviewStore:
        """Return the in-memory order preview store."""
        return self.schwab.preview_store

    @property
    def tools(self) -> ToolsClient:
        """Return the typed tools client facade."""
        return self.schwab.tools

    @property
    def accounts(self) -> AccountClient:
        """Return the typed accounts client facade."""
        return self.schwab.accounts

    @property
    def price_history(self) -> PriceHistoryClient:
        """Return the typed price-history client facade."""
        return self.schwab.price_history

    @property
    def options(self) -> OptionsClient:
        """Return the typed options client facade."""
        return self.schwab.options

    @property
    def orders(self) -> OrdersClient:
        """Return the typed orders client facade."""
        return self.schwab.orders

    @property
    def quotes(self) -> QuotesClient:
        """Return the typed quotes client facade."""
        return self.schwab.quotes

    @property
    def transactions(self) -> TransactionsClient:
        """Return the typed transactions client facade."""
        return self.schwab.transactions


__all__ = ["SchwabServerContext", "SchwabContext"]
