from __future__ import annotations

import time
from typing import Any
from collections.abc import Sequence

import pytest
from starlette.testclient import TestClient

import schwab_mcp.admin.app as admin_app_module
from schwab_mcp.admin.app import create_admin_app
from schwab_mcp.db import DatabaseManager
from schwab_mcp.remote.config import AdminConfig


class FakeDatabaseManager(DatabaseManager):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        return []

    async def execute_many(
        self, sql: str, params_seq: Sequence[Sequence[Any]]
    ) -> None:
        pass


class FakeTokenStorage:
    def __init__(self, token: dict[str, Any] | None = None) -> None:
        self._token = token
        self.written: list[dict[str, Any]] = []

    async def ensure_table(self) -> None:
        pass

    async def load_async(self) -> dict[str, Any]:
        if self._token is None:
            raise FileNotFoundError("no token")
        return self._token

    async def write_async(self, token: dict[str, Any]) -> None:
        self._token = token
        self.written.append(token)


class FakeAuthContext:
    authorization_url = "https://api.schwabapi.com/authorize?client_id=test"


class FakeSchwabAuth:
    @staticmethod
    def get_auth_context(client_id: str, callback_url: str) -> FakeAuthContext:
        return FakeAuthContext()

    @staticmethod
    def client_from_received_url(*args: Any, **kwargs: Any) -> None:
        return None


_VALID_CONFIG = AdminConfig(
    schwab_client_id="test-id",
    schwab_client_secret="test-secret",
    schwab_callback_url="https://admin.authority.bot/datareceived",
    db_instance="proj:region:inst",
    db_password="pass",
)


def _make_token() -> dict[str, Any]:
    return {
        "access_token": "test_at",
        "refresh_token": "test_rt",
        "creation_timestamp": time.time(),
    }


@pytest.fixture
def fake_storage() -> FakeTokenStorage:
    return FakeTokenStorage(token=_make_token())


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, fake_storage: FakeTokenStorage) -> Any:
    fake_db = FakeDatabaseManager()
    monkeypatch.setattr(
        admin_app_module, "CloudSQLManager", lambda config: fake_db
    )
    monkeypatch.setattr(
        admin_app_module, "PostgresTokenStorage", lambda db: fake_storage
    )
    return create_admin_app(_VALID_CONFIG)


@pytest.fixture
def client(app: Any):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# TestAdminDashboard
# ---------------------------------------------------------------------------


class TestAdminDashboard:
    def test_index_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Schwab MCP Admin" in resp.text

    def test_index_shows_token_status(self, client: TestClient) -> None:
        resp = client.get("/")
        assert "Valid" in resp.text

    def test_index_shows_missing_when_no_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_db = FakeDatabaseManager()
        no_token_storage = FakeTokenStorage(token=None)
        monkeypatch.setattr(
            admin_app_module, "CloudSQLManager", lambda config: fake_db
        )
        monkeypatch.setattr(
            admin_app_module, "PostgresTokenStorage", lambda db: no_token_storage
        )
        app = create_admin_app(_VALID_CONFIG)
        with TestClient(app) as c:
            resp = c.get("/")
            assert resp.status_code == 200
            assert "Missing" in resp.text


# ---------------------------------------------------------------------------
# TestSchwabAuth
# ---------------------------------------------------------------------------


class TestSchwabAuth:
    def test_auth_start_redirects(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        monkeypatch.setattr(admin_app_module, "schwab_auth", FakeSchwabAuth)
        resp = client.get("/schwab/auth", follow_redirects=False)
        assert resp.status_code == 302
        assert "schwabapi.com" in resp.headers["location"]


# ---------------------------------------------------------------------------
# TestCallback
# ---------------------------------------------------------------------------


class TestCallback:
    def test_callback_without_code_returns_400(
        self, client: TestClient
    ) -> None:
        resp = client.get("/datareceived")
        assert resp.status_code == 400

    def test_callback_without_state_and_no_pending_returns_400(
        self, client: TestClient
    ) -> None:
        resp = client.get("/datareceived?code=xyz")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestStatus
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_returns_json(self, client: TestClient) -> None:
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "schwab-mcp-admin"
        assert data["status"] == "ok"

    def test_status_includes_token_info(self, client: TestClient) -> None:
        resp = client.get("/status")
        data = resp.json()
        assert data["exists"] is True


# ---------------------------------------------------------------------------
# TestConfigValidation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_invalid_config_raises(self) -> None:
        bad_config = AdminConfig(
            schwab_client_id="",
            schwab_client_secret="",
        )
        with pytest.raises(ValueError, match="Invalid admin configuration"):
            create_admin_app(bad_config)
