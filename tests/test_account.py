from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Any

from schwab_mcp.tools import account
from conftest import make_ctx, run


class DummyAccountClient:
    Account = SimpleNamespace(
        Fields=Enum("Fields", "POSITIONS"),
    )

    def __init__(self):
        self.captured: dict[str, Any] = {}

    async def get_account_numbers(self, *args, **kwargs):
        self.captured = {
            "method": "get_account_numbers",
            "args": args,
            "kwargs": kwargs,
        }
        return None

    async def get_accounts(self, *args, **kwargs):
        self.captured = {"method": "get_accounts", "args": args, "kwargs": kwargs}
        return None

    async def get_account(self, *args, **kwargs):
        self.captured = {"method": "get_account", "args": args, "kwargs": kwargs}
        return None

    async def get_user_preferences(self, *args, **kwargs):
        self.captured = {
            "method": "get_user_preferences",
            "args": args,
            "kwargs": kwargs,
        }
        return None


class TestGetAccountNumbers:
    def test_calls_client_method(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value=[{"accountNumber": "123", "hashValue": "abc123"}]
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account_numbers(ctx))

        assert result == [{"accountNumber": "123", "hashValue": "abc123"}]
        assert captured["func"].__name__ == "get_account_numbers"


class TestGetAccounts:
    def test_calls_client_method(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value=[{"securitiesAccount": {"accountNumber": "123"}}]
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx))

        assert result == [{"securitiesAccount": {"accountNumber": "123"}}]
        assert captured["func"].__name__ == "get_accounts"


class TestGetAccountsWithPositions:
    def test_calls_client_with_positions_field(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value=[{"securitiesAccount": {"positions": []}}]
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts_with_positions(ctx))

        assert result == [{"securitiesAccount": {"positions": []}}]
        assert captured["func"].__name__ == "get_accounts"
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]


class TestGetAccount:
    def test_calls_client_with_account_hash(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value={"securitiesAccount": {"accountNumber": "456"}}
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash456"))

        assert result == {"securitiesAccount": {"accountNumber": "456"}}
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash456",)


class TestGetAccountWithPositions:
    def test_calls_client_with_hash_and_positions_field(
        self, monkeypatch, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(
            return_value={"securitiesAccount": {"positions": [{"symbol": "SPY"}]}}
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account_with_positions(ctx, "hash789"))

        assert result == {"securitiesAccount": {"positions": [{"symbol": "SPY"}]}}
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash789",)
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]


class TestGetUserPreferences:
    def test_calls_client_method(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value={"accounts": [{"displayAcctId": "...1234"}]}
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_user_preferences(ctx))

        assert result == {"accounts": [{"displayAcctId": "...1234"}]}
        assert captured["func"].__name__ == "get_user_preferences"
