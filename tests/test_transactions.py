from __future__ import annotations

import datetime
from enum import Enum
from typing import Any

import pytest

from schwab_mcp.tools import transactions
from conftest import make_ctx, run


class DummyTransactionsClient:
    class Transaction:
        TransactionType = Enum(
            "TransactionType",
            "TRADE DIVIDEND_OR_INTEREST ACH_RECEIPT ACH_DISBURSEMENT",
        )

    def __init__(self):
        self.captured: dict[str, Any] = {}

    async def get_transactions(self, *args, **kwargs):
        self.captured = {"method": "get_transactions", "args": args, "kwargs": kwargs}
        return None

    async def get_transaction(self, *args, **kwargs):
        self.captured = {"method": "get_transaction", "args": args, "kwargs": kwargs}
        return None


class TestGetTransactions:
    @pytest.fixture
    def client(self):
        return DummyTransactionsClient()

    @pytest.fixture
    def ctx(self, client):
        return make_ctx(client)

    def test_calls_client_with_account_hash(
        self, monkeypatch, ctx, client, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        result = run(transactions.get_transactions(ctx, "hash123"))

        assert result == []
        assert captured["args"] == ("hash123",)
        assert captured["kwargs"]["start_date"] is None
        assert captured["kwargs"]["end_date"] is None
        assert captured["kwargs"]["transaction_types"] is None
        assert captured["kwargs"]["symbol"] is None

    def test_parses_date_strings(self, monkeypatch, ctx, client, fake_call_factory):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        run(
            transactions.get_transactions(
                ctx,
                "hash123",
                start_date="2024-01-15",
                end_date="2024-02-15",
            )
        )

        assert captured["kwargs"]["start_date"] == datetime.date(2024, 1, 15)
        assert captured["kwargs"]["end_date"] == datetime.date(2024, 2, 15)

    def test_maps_single_transaction_type_string(
        self, monkeypatch, ctx, client, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        run(
            transactions.get_transactions(
                ctx,
                "hash123",
                transaction_type="trade",
            )
        )

        assert captured["kwargs"]["transaction_types"] == [
            client.Transaction.TransactionType.TRADE
        ]

    def test_maps_comma_separated_transaction_types(
        self, monkeypatch, ctx, client, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        run(
            transactions.get_transactions(
                ctx,
                "hash123",
                transaction_type="trade, dividend_or_interest",
            )
        )

        assert captured["kwargs"]["transaction_types"] == [
            client.Transaction.TransactionType.TRADE,
            client.Transaction.TransactionType.DIVIDEND_OR_INTEREST,
        ]

    def test_maps_list_of_transaction_types(
        self, monkeypatch, ctx, client, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        run(
            transactions.get_transactions(
                ctx,
                "hash123",
                transaction_type=["ACH_RECEIPT", "ACH_DISBURSEMENT"],
            )
        )

        assert captured["kwargs"]["transaction_types"] == [
            client.Transaction.TransactionType.ACH_RECEIPT,
            client.Transaction.TransactionType.ACH_DISBURSEMENT,
        ]

    def test_passes_symbol_filter(self, monkeypatch, ctx, client, fake_call_factory):
        captured, fake_call = fake_call_factory(return_value=[])

        monkeypatch.setattr(transactions, "call", fake_call)

        run(
            transactions.get_transactions(
                ctx,
                "hash123",
                symbol="SPY",
            )
        )

        assert captured["kwargs"]["symbol"] == "SPY"

    def test_all_parameters_combined(self, monkeypatch, ctx, client, fake_call_factory):
        captured, fake_call = fake_call_factory(return_value=[{"id": "txn1"}])

        monkeypatch.setattr(transactions, "call", fake_call)

        result = run(
            transactions.get_transactions(
                ctx,
                "hash456",
                start_date="2024-03-01",
                end_date="2024-03-31",
                transaction_type=["TRADE"],
                symbol="AAPL",
            )
        )

        assert result == [{"id": "txn1"}]
        assert captured["args"] == ("hash456",)
        assert captured["kwargs"]["start_date"] == datetime.date(2024, 3, 1)
        assert captured["kwargs"]["end_date"] == datetime.date(2024, 3, 31)
        assert captured["kwargs"]["transaction_types"] == [
            client.Transaction.TransactionType.TRADE
        ]
        assert captured["kwargs"]["symbol"] == "AAPL"


class TestGetTransaction:
    @pytest.fixture
    def client(self):
        return DummyTransactionsClient()

    @pytest.fixture
    def ctx(self, client):
        return make_ctx(client)

    def test_calls_client_with_correct_args(
        self, monkeypatch, ctx, client, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(
            return_value={"transactionId": "txn123", "type": "TRADE"}
        )

        monkeypatch.setattr(transactions, "call", fake_call)

        result = run(transactions.get_transaction(ctx, "hash123", "txn456"))

        assert result == {"transactionId": "txn123", "type": "TRADE"}
        assert captured["func"] == client.get_transaction
        assert captured["args"] == ("hash123", "txn456")
