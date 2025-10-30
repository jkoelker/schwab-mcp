from __future__ import annotations

from typing import Any, Awaitable, Protocol


class EnumLookup(Protocol):
    __members__: dict[str, Any]

    def __getitem__(self, key: str) -> Any: ...


class PriceHistoryNamespace(Protocol):
    PeriodType: EnumLookup
    Period: EnumLookup
    FrequencyType: EnumLookup


class PriceHistoryClient(Protocol):
    PriceHistory: PriceHistoryNamespace

    def get_price_history(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_minute(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_five_minutes(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_ten_minutes(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_fifteen_minutes(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_thirty_minutes(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_day(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_price_history_every_week(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...


class OptionsNamespace(Protocol):
    ContractType: EnumLookup
    Strategy: EnumLookup
    StrikeRange: EnumLookup
    ExpirationMonth: EnumLookup
    Type: EnumLookup


class OptionsClient(Protocol):
    Options: OptionsNamespace

    def get_option_chain(self, symbol: str, **kwargs: Any) -> Awaitable[Any]: ...

    def get_option_expiration_chain(
        self, symbol: str, **kwargs: Any
    ) -> Awaitable[Any]: ...


class QuoteFieldsNamespace(Protocol):
    def __getitem__(self, key: str) -> Any: ...


class QuoteNamespace(Protocol):
    Fields: QuoteFieldsNamespace


class QuotesClient(Protocol):
    Quote: QuoteNamespace

    def get_quotes(self, symbols: list[str], **kwargs: Any) -> Awaitable[Any]: ...


class MarketHoursNamespace(Protocol):
    Market: EnumLookup


class MoversNamespace(Protocol):
    Index: EnumLookup
    SortOrder: EnumLookup
    Frequency: EnumLookup


class InstrumentNamespace(Protocol):
    Projection: EnumLookup


class ToolsClient(Protocol):
    MarketHours: MarketHoursNamespace
    Movers: MoversNamespace
    Instrument: InstrumentNamespace

    def get_market_hours(self, markets: list[Any], **kwargs: Any) -> Awaitable[Any]: ...

    def get_movers(self, index: Any, **kwargs: Any) -> Awaitable[Any]: ...

    def get_instruments(self, symbol: str, **kwargs: Any) -> Awaitable[Any]: ...


class AccountFieldsNamespace(Protocol):
    POSITIONS: Any


class AccountNamespace(Protocol):
    Fields: AccountFieldsNamespace


class AccountClient(Protocol):
    Account: AccountNamespace

    def get_account_numbers(self, **kwargs: Any) -> Awaitable[Any]: ...

    def get_accounts(self, **kwargs: Any) -> Awaitable[Any]: ...

    def get_account(self, account_hash: str, **kwargs: Any) -> Awaitable[Any]: ...

    def get_user_preferences(self, **kwargs: Any) -> Awaitable[Any]: ...


class OrderStatusNamespace(Protocol):
    def __getitem__(self, key: str) -> Any: ...


class OrderNamespace(Protocol):
    Status: OrderStatusNamespace


class OrdersClient(Protocol):
    Order: OrderNamespace

    def get_orders_for_account(
        self, account_hash: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def get_order(
        self, order_id: str, account_hash: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def cancel_order(
        self, order_id: str, account_hash: str, **kwargs: Any
    ) -> Awaitable[Any]: ...

    def place_order(self, account_hash: str, **kwargs: Any) -> Awaitable[Any]: ...


class TransactionTypeNamespace(Protocol):
    def __getitem__(self, key: str) -> Any: ...


class TransactionNamespace(Protocol):
    TransactionType: TransactionTypeNamespace


class TransactionsClient(Protocol):
    Transaction: TransactionNamespace

    def get_transactions(self, account_hash: str, **kwargs: Any) -> Awaitable[Any]: ...

    def get_transaction(
        self, account_hash: str, transaction_id: str, **kwargs: Any
    ) -> Awaitable[Any]: ...
