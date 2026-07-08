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

_SAMPLE_IDENTITY_MAP: dict[str, account.AccountIdentity] = {
    "123": account.AccountIdentity(account_hash="hash_abc", nickname="My Margin"),
}


# ---------------------------------------------------------------------------
# Tests for _get_identity_map
# ---------------------------------------------------------------------------


class TestGetIdentityMap:
    def test_builds_map_from_numbers_and_prefs(self, monkeypatch):
        numbers_payload = [{"accountNumber": "123", "hashValue": "hash_abc"}]
        prefs_payload = {
            "accounts": [{"accountNumber": "123", "nickName": "My Margin"}]
        }
        call_returns = iter([numbers_payload, prefs_payload])

        async def fake_call(func, *args, **kwargs):
            return next(call_returns)

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert result == {
            "123": account.AccountIdentity(
                account_hash="hash_abc", nickname="My Margin"
            )
        }

    def test_missing_nickname_yields_none(self, monkeypatch):
        numbers_payload = [{"accountNumber": "456", "hashValue": "hash_def"}]
        prefs_payload = {"accounts": []}  # no entry for 456
        call_returns = iter([numbers_payload, prefs_payload])

        async def fake_call(func, *args, **kwargs):
            return next(call_returns)

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert result == {
            "456": account.AccountIdentity(account_hash="hash_def", nickname=None)
        }

    def test_empty_payloads_yield_empty_map(self, monkeypatch):
        async def fake_call(func, *args, **kwargs):
            return None

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert result == {}

    def test_malformed_numbers_entry_skipped(self, monkeypatch):
        numbers_payload = [
            {"accountNumber": "123"},  # missing hashValue
            "not-a-dict",
            {"accountNumber": "456", "hashValue": "hash_def"},
        ]
        prefs_payload = {}
        call_returns = iter([numbers_payload, prefs_payload])

        async def fake_call(func, *args, **kwargs):
            return next(call_returns)

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert "123" not in result  # missing hashValue skipped
        assert result["456"].account_hash == "hash_def"

    def test_non_string_nickname_normalized_to_none(self, monkeypatch):
        numbers_payload = [{"accountNumber": "123", "hashValue": "hash_abc"}]
        prefs_payload = {"accounts": [{"accountNumber": "123", "nickName": 12345}]}
        call_returns = iter([numbers_payload, prefs_payload])

        async def fake_call(func, *args, **kwargs):
            return next(call_returns)

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert result["123"].nickname is None

    def test_api_error_is_best_effort_and_yields_empty_map(self, monkeypatch):
        from schwab_mcp.tools.utils import SchwabAPIError

        async def fake_call(func, *args, **kwargs):
            raise SchwabAPIError(status_code=500, url="https://example.com", body="")

        monkeypatch.setattr(account, "call", fake_call)
        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account._get_identity_map(ctx))

        assert result == {}


# ---------------------------------------------------------------------------
# Tests for _enrich_with_identity
# ---------------------------------------------------------------------------


class TestEnrichWithIdentity:
    def test_list_shape_injects_fields(self):
        payload = [{"securitiesAccount": {"accountNumber": "123"}}]
        result = account._enrich_with_identity(payload, _SAMPLE_IDENTITY_MAP)
        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_dict_shape_injects_fields(self):
        payload = {"securitiesAccount": {"accountNumber": "123"}}
        result = account._enrich_with_identity(payload, _SAMPLE_IDENTITY_MAP)
        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_no_match_yields_null_fields(self):
        payload = {"securitiesAccount": {"accountNumber": "UNKNOWN"}}
        result = account._enrich_with_identity(payload, _SAMPLE_IDENTITY_MAP)
        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountHash"] is None
        assert sec["nickname"] is None

    def test_null_fields_always_present(self):
        """Both keys must be present even when identity map is empty."""
        payload = {"securitiesAccount": {"accountNumber": "999"}}
        result = account._enrich_with_identity(payload, {})
        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert "accountHash" in sec
        assert "nickname" in sec
        assert sec["accountHash"] is None
        assert sec["nickname"] is None

    def test_list_item_without_securities_account_passes_through(self):
        payload = [{"other": "data"}, {"securitiesAccount": {"accountNumber": "123"}}]
        result = account._enrich_with_identity(payload, _SAMPLE_IDENTITY_MAP)
        assert isinstance(result, list)
        assert result[0] == {"other": "data"}
        assert result[1]["securitiesAccount"]["accountHash"] == "hash_abc"

    def test_fallback_hash_used_when_no_match(self):
        payload = {"securitiesAccount": {"accountNumber": "UNKNOWN"}}
        result = account._enrich_with_identity(
            payload, {}, fallback_hash="requested_hash"
        )
        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "requested_hash"
        assert sec["nickname"] is None

    def test_fallback_hash_ignored_when_match_found(self):
        payload = {"securitiesAccount": {"accountNumber": "123"}}
        result = account._enrich_with_identity(
            payload, _SAMPLE_IDENTITY_MAP, fallback_hash="requested_hash"
        )
        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"


# ---------------------------------------------------------------------------
# TestGetAccounts — monkeypatch _get_identity_map for pruning/verbose tests
# ---------------------------------------------------------------------------


class TestGetAccounts:
    def _patch_identity(self, monkeypatch, identity_map=None):
        if identity_map is None:
            identity_map = _SAMPLE_IDENTITY_MAP

        async def fake_get_identity_map(ctx):
            return identity_map

        monkeypatch.setattr(account, "_get_identity_map", fake_get_identity_map)

    def test_calls_client_method(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value=[{"securitiesAccount": {"accountNumber": "123"}}]
        )
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, verbose=True))

        assert isinstance(result, list)
        assert captured["func"].__name__ == "get_accounts"

    def test_compact_default_strips_extra_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx))

        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
        assert sec["accountNumber"] == "123"
        assert sec["type"] == "MARGIN"
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        balances = sec["currentBalances"]
        assert set(balances.keys()) <= account._COMPACT_BALANCE_FIELDS
        assert "maintenanceRequirement" not in balances
        assert "totalCash" not in balances
        assert balances["equity"] == 50000.0

    def test_compact_includes_identity_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx))

        sec = result[0]["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_verbose_includes_identity_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, verbose=True))

        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_no_identity_match_yields_null_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        self._patch_identity(monkeypatch, identity_map={})
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx))

        sec = result[0]["securitiesAccount"]
        assert sec["accountHash"] is None
        assert sec["nickname"] is None

    def test_default_does_not_request_positions_field(
        self, monkeypatch, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=_RAW_LIST_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        run(account.get_accounts(ctx))

        assert "fields" not in captured["kwargs"]

    def test_include_positions_requests_positions_field(
        self, monkeypatch, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(
            return_value=[
                {"securitiesAccount": {"accountNumber": "123", "positions": []}}
            ]
        )
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, include_positions=True, verbose=True))

        assert isinstance(result, list)
        assert captured["func"].__name__ == "get_accounts"
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]

    def test_include_positions_compact_default_prunes_positions(
        self, monkeypatch, fake_call_factory
    ):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_WITH_POSITIONS)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, include_positions=True))

        assert isinstance(result, list)
        sec = result[0]["securitiesAccount"]
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
        assert "maintenanceRequirement" not in pos

    def test_include_positions_verbose_returns_enriched_payload(
        self, monkeypatch, fake_call_factory
    ):
        _, fake_call = fake_call_factory(return_value=_RAW_LIST_WITH_POSITIONS)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_accounts(ctx, include_positions=True, verbose=True))

        assert isinstance(result, list)
        # enrichment still applied in verbose mode
        sec = result[0]["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"


# ---------------------------------------------------------------------------
# TestGetAccount — monkeypatch _get_identity_map for pruning/verbose tests
# ---------------------------------------------------------------------------


class TestGetAccount:
    def _patch_identity(self, monkeypatch, identity_map=None):
        if identity_map is None:
            identity_map = _SAMPLE_IDENTITY_MAP

        async def fake_get_identity_map(ctx):
            return identity_map

        monkeypatch.setattr(account, "_get_identity_map", fake_get_identity_map)

    def test_calls_client_with_account_hash(self, monkeypatch, fake_call_factory):
        captured, fake_call = fake_call_factory(
            return_value={"securitiesAccount": {"accountNumber": "123"}}
        )
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash_abc", verbose=True))

        assert isinstance(result, dict)
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash_abc",)

    def test_compact_default_strips_extra_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash_abc"))

        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountNumber"] == "123"
        assert "initialBalances" not in sec
        assert "projectedBalances" not in sec
        balances = sec["currentBalances"]
        assert set(balances.keys()) <= account._COMPACT_BALANCE_FIELDS
        assert "maintenanceRequirement" not in balances

    def test_compact_includes_identity_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash_abc"))

        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_verbose_includes_identity_fields(self, monkeypatch, fake_call_factory):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash_abc", verbose=True))

        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] == "My Margin"

    def test_no_identity_match_falls_back_to_requested_hash(
        self, monkeypatch, fake_call_factory
    ):
        """get_account() already knows account_hash; enrichment falling short
        should not discard it."""
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        self._patch_identity(monkeypatch, identity_map={})
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash_abc"))

        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"
        assert sec["nickname"] is None

    def test_default_does_not_request_positions_field(
        self, monkeypatch, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(return_value=_RAW_DICT_PAYLOAD)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        run(account.get_account(ctx, "hash_abc"))

        assert "fields" not in captured["kwargs"]

    def test_include_positions_requests_positions_field(
        self, monkeypatch, fake_call_factory
    ):
        captured, fake_call = fake_call_factory(
            return_value={
                "securitiesAccount": {
                    "accountNumber": "123",
                    "positions": [{"symbol": "SPY"}],
                }
            }
        )
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(
            account.get_account(ctx, "hash789", include_positions=True, verbose=True)
        )

        assert isinstance(result, dict)
        assert captured["func"].__name__ == "get_account"
        assert captured["args"] == ("hash789",)
        assert captured["kwargs"]["fields"] == [client.Account.Fields.POSITIONS]

    def test_include_positions_compact_default_prunes_positions(
        self, monkeypatch, fake_call_factory
    ):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_WITH_POSITIONS)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(account.get_account(ctx, "hash789", include_positions=True))

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

    def test_include_positions_verbose_returns_enriched_payload(
        self, monkeypatch, fake_call_factory
    ):
        _, fake_call = fake_call_factory(return_value=_RAW_DICT_WITH_POSITIONS)
        self._patch_identity(monkeypatch)
        monkeypatch.setattr(account, "call", fake_call)

        client = DummyAccountClient()
        ctx = make_ctx(client)
        result = run(
            account.get_account(ctx, "hash789", include_positions=True, verbose=True)
        )

        assert isinstance(result, dict)
        sec = result["securitiesAccount"]
        assert sec["accountHash"] == "hash_abc"


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
