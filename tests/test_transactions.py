from __future__ import annotations

import datetime
from enum import Enum
from typing import Any

import pytest
from conftest import make_ctx, run

from schwab_mcp.tools import transactions


class DummyTransactionsClient:
    class Transactions:
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


TransactionType = DummyTransactionsClient.Transactions.TransactionType


class TestGetTransactions:
    @pytest.fixture
    def client(self):
        return DummyTransactionsClient()

    @pytest.fixture
    def ctx(self, client):
        return make_ctx(client)

    @pytest.fixture
    def captured(self, monkeypatch, fake_call_factory) -> dict[str, Any]:
        """Stub call() to return an empty list and record what it receives."""
        recorded, fake_call = fake_call_factory(return_value=[])
        monkeypatch.setattr(transactions, "call", fake_call)
        return recorded

    def test_calls_client_with_account_hash(self, ctx, captured):
        result = run(transactions.get_transactions(ctx, "hash123"))

        assert result == []
        assert captured["args"] == ("hash123",)
        assert captured["kwargs"]["start_date"] is None
        assert captured["kwargs"]["end_date"] is None
        assert captured["kwargs"]["transaction_types"] is None
        assert captured["kwargs"]["symbol"] is None

    def test_parses_date_strings(self, ctx, captured):
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

    @pytest.mark.parametrize(
        "transaction_type,expected",
        [
            pytest.param("trade", [TransactionType.TRADE], id="single-string"),
            pytest.param(
                "trade, dividend_or_interest",
                [TransactionType.TRADE, TransactionType.DIVIDEND_OR_INTEREST],
                id="comma-separated",
            ),
            pytest.param(
                ["ACH_RECEIPT", "ACH_DISBURSEMENT"],
                [TransactionType.ACH_RECEIPT, TransactionType.ACH_DISBURSEMENT],
                id="list",
            ),
        ],
    )
    def test_maps_transaction_type_input(self, ctx, captured, transaction_type, expected):
        run(transactions.get_transactions(ctx, "hash123", transaction_type=transaction_type))

        assert captured["kwargs"]["transaction_types"] == expected

    def test_passes_symbol_filter(self, ctx, captured):
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
        assert captured["kwargs"]["transaction_types"] == [client.Transactions.TransactionType.TRADE]
        assert captured["kwargs"]["symbol"] == "AAPL"


class TestGetTransaction:
    @pytest.fixture
    def client(self):
        return DummyTransactionsClient()

    @pytest.fixture
    def ctx(self, client):
        return make_ctx(client)

    def test_calls_client_with_correct_args(self, monkeypatch, ctx, client, fake_call_factory):
        captured, fake_call = fake_call_factory(return_value={"transactionId": "txn123", "type": "TRADE"})

        monkeypatch.setattr(transactions, "call", fake_call)

        result = run(transactions.get_transaction(ctx, "hash123", "txn456"))

        assert result == {"transactionId": "txn123", "type": "TRADE"}
        assert captured["func"] == client.get_transaction
        assert captured["args"] == ("hash123", "txn456")
