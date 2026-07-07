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


# ---------------------------------------------------------------------------
# Sample raw payloads
# ---------------------------------------------------------------------------

_RAW_SEC_ACCOUNT = {
    "type": "MARGIN",
    "accountNumber": "123",
    "roundTrips": 0,
    "isDayTrader": False,
    "currentBalances": {
        "equity": 50000.0,
        "buyingPower": 20000.0,
        "cashBalance": 5000.0,
        "cashAvailableForTrading": 4000.0,
        "liquidationValue": 49000.0,
        "maintenanceRequirement": 1000.0,  # should be stripped
        "totalCash": 6000.0,  # should be stripped
    },
    "initialBalances": {"equity": 48000.0},  # should be dropped in compact
    "projectedBalances": {"equity": 51000.0},  # should be dropped in compact
}

_RAW_POSITION = {
    "longQuantity": 10,
    "shortQuantity": 0,
    "averagePrice": 150.0,
    "currentDayProfitLoss": 100.0,
    "currentDayProfitLossPercentage": 0.01,
    "marketValue": 1550.0,
    "maintenanceRequirement": 0.0,
    "settledLongQuantity": 10,  # should be stripped
    "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
}

_RAW_SEC_ACCOUNT_WITH_POSITIONS = {**_RAW_SEC_ACCOUNT, "positions": [_RAW_POSITION]}

_RAW_LIST_PAYLOAD = [{"securitiesAccount": _RAW_SEC_ACCOUNT}]
_RAW_LIST_WITH_POSITIONS = [{"securitiesAccount": _RAW_SEC_ACCOUNT_WITH_POSITIONS}]
_RAW_DICT_PAYLOAD = {"securitiesAccount": _RAW_SEC_ACCOUNT}
_RAW_DICT_WITH_POSITIONS = {"securitiesAccount": _RAW_SEC_ACCOUNT_WITH_POSITIONS}


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
        result = run(account.get_accounts(ctx, verbose=True))

        assert result == [{"securitiesAccount": {"accountNumber": "123"}}]
        assert captured["func"].__name__ == "get_accounts"

    def test_compact_default_strips_extra_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx))

        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
        # identity fields kept
        assert sec["accountNumber"] == "123"
        assert sec["type"] == "MARGIN"
        # initialBalances / projectedBalances dropped
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        # only allowlisted balance fields
        balances = sec["currentBalances"]
        assert set(balances.keys()) <= account._COMPACT_BALANCE_FIELDS
        assert "maintenanceRequirement" not in balances
        assert "totalCash" not in balances
        assert balances["equity"] == 50000.0

    def test_verbose_returns_raw_payload(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, verbose=True))

        assert result is _RAW_LIST_PAYLOAD


class TestGetAccountsWithPositions:
    def test_calls_client_with_positions_field(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value=[{"securitiesAccount": {"positions": []}}]
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts_with_positions(ctx, verbose=True))

        assert result == [{"securitiesAccount": {"positions": []}}]
        assert captured["func"].__name__ == "get_accounts"
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]

    def test_compact_default_prunes_positions(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_WITH_POSITIONS)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts_with_positions(ctx))

        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        positions = sec["positions"]
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "AAPL"
        assert pos["quantity"] == 10  # longQuantity 10 - shortQuantity 0
        assert pos["marketValue"] == 1550.0
        assert pos["averagePrice"] == 150.0
        assert pos["unrealizedPL"] == 100.0
        assert "settledLongQuantity" not in pos
        assert "maintenanceRequirement" not in pos

    def test_verbose_returns_raw_payload(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_WITH_POSITIONS)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts_with_positions(ctx, verbose=True))

        assert result is _RAW_LIST_WITH_POSITIONS


class TestGetAccount:
    def test_calls_client_with_account_hash(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value={"securitiesAccount": {"accountNumber": "456"}}
        )

        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash456", verbose=True))

        assert result == {"securitiesAccount": {"accountNumber": "456"}}
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash456",)

    def test_compact_default_strips_extra_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash456"))

        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountNumber"] == "123"
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        balances = sec["currentBalances"]
        assert set(balances.keys()) <= account._COMPACT_BALANCE_FIELDS
        assert "maintenanceRequirement" not in balances

    def test_verbose_returns_raw_payload(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash456", verbose=True))

        assert result is _RAW_DICT_PAYLOAD


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
        result = run(account.get_account_with_positions(ctx, "hash789", verbose=True))

        assert result == {"securitiesAccount": {"positions": [{"symbol": "SPY"}]}}
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash789",)
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]

    def test_compact_default_prunes_positions(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_WITH_POSITIONS)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account_with_positions(ctx, "hash789"))

        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        positions = sec["positions"]
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "AAPL"
        assert pos["quantity"] == 10
        assert pos["marketValue"] == 1550.0
        assert pos["averagePrice"] == 150.0
        assert pos["unrealizedPL"] == 100.0
        assert "settledLongQuantity" not in pos

    def test_verbose_returns_raw_payload(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_WITH_POSITIONS)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account_with_positions(ctx, "hash789", verbose=True))

        assert result is _RAW_DICT_WITH_POSITIONS


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


# ---------------------------------------------------------------------------
# Edge case: net quantity with both longQuantity and shortQuantity nonzero
# ---------------------------------------------------------------------------


def test_prune_position_net_quantity_long_minus_short():
    position = {
        "longQuantity": 10,
        "shortQuantity": 3,
        "averagePrice": 200.0,
        "currentDayProfitLoss": -50.0,
        "marketValue": 1400.0,
        "instrument": {"symbol": "TSLA", "assetType": "EQUITY"},
    }
    pruned = account._prune_position(position)
    assert pruned["quantity"] == 7  # 10 - 3
    assert pruned["symbol"] == "TSLA"
    assert pruned["marketValue"] == 1400.0
    assert pruned["unrealizedPL"] == -50.0


# ---------------------------------------------------------------------------
# Fix #2: _prune_position type guards for instrument / quantities
# ---------------------------------------------------------------------------


def test_prune_position_instrument_none_omits_symbol():
    """When instrument is None (not a dict), symbol key must be absent."""
    position = {"longQuantity": 5, "shortQuantity": 0, "instrument": None}
    pruned = account._prune_position(position)
    assert "symbol" not in pruned
    assert pruned["quantity"] == 5


def test_prune_position_instrument_missing_omits_symbol():
    """When instrument key is absent entirely, symbol key must be absent."""
    position = {"longQuantity": 2, "shortQuantity": 0}
    pruned = account._prune_position(position)
    assert "symbol" not in pruned
    assert pruned["quantity"] == 2


def test_prune_position_non_numeric_quantities_default_to_zero():
    """Non-numeric longQuantity/shortQuantity must default to 0."""
    position = {
        "longQuantity": "ten",
        "shortQuantity": None,
        "instrument": {"symbol": "X"},
    }
    pruned = account._prune_position(position)
    assert pruned["quantity"] == 0


# ---------------------------------------------------------------------------
# Fix #3: _prune_securities_account guards for currentBalances / positions
# ---------------------------------------------------------------------------


def test_prune_securities_account_none_current_balances():
    """currentBalances=None must produce an empty dict, not raise."""
    sec = {
        "type": "CASH",
        "accountNumber": "999",
        "currentBalances": None,
    }
    pruned = account._prune_securities_account(sec)
    assert pruned["currentBalances"] == {}


def test_prune_securities_account_positions_not_a_list_passthrough():
    """When positions is not a list, it must be passed through unchanged."""
    sec = {
        "type": "CASH",
        "accountNumber": "999",
        "currentBalances": {},
        "positions": {"unexpected": "dict"},
    }
    pruned = account._prune_securities_account(sec)
    assert pruned["positions"] == {"unexpected": "dict"}


# ---------------------------------------------------------------------------
# Fix #4: _prune_account_response guards securitiesAccount type
# ---------------------------------------------------------------------------


def test_prune_account_response_securities_account_not_dict_passthrough():
    """When securitiesAccount is not a dict, the original value must be kept."""
    payload = {"securitiesAccount": "bad-value"}
    result = account._prune_account_response(payload)
    assert result == {"securitiesAccount": "bad-value"}


def test_prune_account_response_list_item_securities_account_not_dict():
    """In a list payload, items where securitiesAccount is not a dict pass through."""
    payload = [{"securitiesAccount": None}, {"securitiesAccount": _RAW_SEC_ACCOUNT}]
    result = account._prune_account_response(payload)
    assert isinstance(result, list)
    # First item unchanged because securitiesAccount is not a dict
    assert result[0] == {"securitiesAccount": None}
    # Second item should be pruned normally
    assert "currentBalances" in result[1]["securitiesAccount"]
