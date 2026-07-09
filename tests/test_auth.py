"""Unit tests for schwab_mcp/auth.py."""

from __future__ import annotations

import queue
from typing import Any
from unittest.mock import MagicMock, patch

import httpx as _httpx
import pytest
from schwab import auth as schwab_auth

from schwab_mcp import auth as mcp_auth, tokens

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

FAKE_CLIENT_ID = "test-client-id"
FAKE_CLIENT_SECRET = "test-client-secret"
VALID_CALLBACK_URL = "https://127.0.0.1:8182"


class DummyClient:
    """Minimal stand-in for AsyncClient / Client."""

    def __init__(self, token_age: float = 0.0):
        self._token_age = token_age

    def token_age(self) -> float:
        return self._token_age


class DummyTokenManager(tokens.Manager):
    """Minimal stand-in for tokens.Manager that avoids touching the filesystem."""

    def __init__(self, *, exists: bool = True, path: str = "/tmp/token.yaml"):
        # Bypass tokens.Manager.__init__ to avoid token_loader/token_writer calls
        self.path = path
        self.load = MagicMock()  # type: ignore[assignment]
        self.write = MagicMock()  # type: ignore[assignment]
        self._exists_flag = exists

    def exists(self) -> bool:
        return self._exists_flag


class DummyAuthContext:
    authorization_url = "https://auth.schwab.com/oauth2/authorize?client_id=x"


# ---------------------------------------------------------------------------
# easy_client tests
# ---------------------------------------------------------------------------


def _make_dummy_client(token_age: float = 0.0) -> DummyClient:
    return DummyClient(token_age=token_age)


@patch("schwab_mcp.auth.client_from_login_flow")
@patch("schwab_mcp.auth.auth.client_from_access_functions")
def test_easy_client_reuses_valid_token(mock_caf: Any, mock_login: Any) -> None:
    """When a fresh token exists, easy_client returns without entering login flow."""
    dummy = _make_dummy_client(token_age=100.0)
    mock_caf.return_value = dummy

    manager = DummyTokenManager(exists=True)
    result = mcp_auth.easy_client(
        FAKE_CLIENT_ID,
        FAKE_CLIENT_SECRET,
        VALID_CALLBACK_URL,
        manager,
        max_token_age=mcp_auth.DEFAULT_MAX_TOKEN_AGE_SECONDS,
    )

    assert result is dummy
    mock_caf.assert_called_once()
    mock_login.assert_not_called()


@patch("schwab_mcp.auth.client_from_login_flow")
@patch("schwab_mcp.auth.auth.client_from_access_functions")
def test_easy_client_falls_through_when_no_token(mock_caf: Any, mock_login: Any) -> None:
    """When no token exists, easy_client delegates to client_from_login_flow."""
    dummy = _make_dummy_client()
    mock_login.return_value = dummy

    manager = DummyTokenManager(exists=False)
    result = mcp_auth.easy_client(
        FAKE_CLIENT_ID,
        FAKE_CLIENT_SECRET,
        VALID_CALLBACK_URL,
        manager,
    )

    assert result is dummy
    mock_caf.assert_not_called()
    mock_login.assert_called_once()


@patch("schwab_mcp.auth.client_from_login_flow")
@patch("schwab_mcp.auth.auth.client_from_access_functions")
def test_easy_client_rejects_stale_token(mock_caf: Any, mock_login: Any) -> None:
    """Token older than max_token_age triggers login flow."""
    max_age = 100
    stale_client = _make_dummy_client(token_age=float(max_age + 1))
    mock_caf.return_value = stale_client

    fresh_client = _make_dummy_client(token_age=0.0)
    mock_login.return_value = fresh_client

    manager = DummyTokenManager(exists=True)
    result = mcp_auth.easy_client(
        FAKE_CLIENT_ID,
        FAKE_CLIENT_SECRET,
        VALID_CALLBACK_URL,
        manager,
        max_token_age=max_age,
    )

    assert result is fresh_client
    mock_login.assert_called_once()


@patch("schwab_mcp.auth.client_from_login_flow")
@patch("schwab_mcp.auth.auth.client_from_access_functions")
def test_easy_client_max_token_age_none_skips_age_check(mock_caf: Any, mock_login: Any) -> None:
    """max_token_age=None disables the age check; any token age is accepted."""
    ancient_client = _make_dummy_client(token_age=99_999_999.0)
    mock_caf.return_value = ancient_client

    manager = DummyTokenManager(exists=True)
    result = mcp_auth.easy_client(
        FAKE_CLIENT_ID,
        FAKE_CLIENT_SECRET,
        VALID_CALLBACK_URL,
        manager,
        max_token_age=None,
    )

    assert result is ancient_client
    mock_login.assert_not_called()


@patch("schwab_mcp.auth.client_from_login_flow")
@patch("schwab_mcp.auth.auth.client_from_access_functions")
def test_easy_client_max_token_age_zero_skips_age_check(mock_caf: Any, mock_login: Any) -> None:
    """max_token_age=0 treats effective age as 0 (no age check), not as 'disable'."""
    # When effective_max_token_age == 0, the condition `> 0` is False → no eviction.
    any_age_client = _make_dummy_client(token_age=50_000.0)
    mock_caf.return_value = any_age_client

    manager = DummyTokenManager(exists=True)
    result = mcp_auth.easy_client(
        FAKE_CLIENT_ID,
        FAKE_CLIENT_SECRET,
        VALID_CALLBACK_URL,
        manager,
        max_token_age=0,
    )

    assert result is any_age_client
    mock_login.assert_not_called()


def test_easy_client_negative_max_token_age_raises() -> None:
    """Negative max_token_age raises ValueError."""
    manager = DummyTokenManager(exists=False)
    with pytest.raises(ValueError, match="max_token_age must be positive"):
        mcp_auth.easy_client(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            VALID_CALLBACK_URL,
            manager,
            max_token_age=-1,
        )


# ---------------------------------------------------------------------------
# client_from_login_flow: hostname validation
# ---------------------------------------------------------------------------


def test_client_from_login_flow_rejects_non_localhost_hostname() -> None:
    """Non-127.0.0.1 hostnames are rejected with a descriptive ValueError."""
    manager = DummyTokenManager(exists=False)
    with pytest.raises(ValueError, match="Disallowed hostname"):
        mcp_auth.client_from_login_flow(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            "https://localhost:8182",
            manager,
        )


def test_client_from_login_flow_rejects_public_hostname() -> None:
    """Public hostnames are also rejected."""
    manager = DummyTokenManager(exists=False)
    with pytest.raises(ValueError, match="Disallowed hostname"):
        mcp_auth.client_from_login_flow(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            "https://example.com:8182",
            manager,
        )


def test_client_from_login_flow_negative_timeout_raises() -> None:
    """Negative callback_timeout raises ValueError before any network activity."""
    manager = DummyTokenManager(exists=False)
    with pytest.raises(ValueError, match="callback_timeout must be positive"):
        mcp_auth.client_from_login_flow(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            VALID_CALLBACK_URL,
            manager,
            callback_timeout=-1.0,
        )


# ---------------------------------------------------------------------------
# client_from_login_flow: happy-path (mocked subprocess + httpx + browser)
# ---------------------------------------------------------------------------


def _make_login_flow_mocks(
    *,
    queue_items: list[Any],
    httpx_connect_error_count: int = 0,
) -> dict[str, Any]:
    """Build a dict of patches that drive client_from_login_flow without I/O."""
    # Process mock: starts immediately, has a pid, never exits early
    mock_process = MagicMock()
    mock_process.pid = 9999
    mock_process.exitcode = None  # server appears to be running

    mock_process_cls = MagicMock(return_value=mock_process)

    # Queue mock
    mock_queue_instance = MagicMock()
    # Simulate httpx.ConnectError a few times before succeeding
    httpx_call_count: list[int] = [0]

    def fake_httpx_get(*args: Any, **kwargs: Any) -> MagicMock:
        httpx_call_count[0] += 1
        if httpx_call_count[0] <= httpx_connect_error_count:
            raise _httpx.ConnectError("not ready")
        return MagicMock()

    # output_queue.get(): first return received_url, then raise Empty
    items = list(queue_items)

    def fake_queue_get(**kwargs: Any) -> str:
        if items:
            return items.pop(0)
        raise queue.Empty

    mock_queue_instance.get.side_effect = fake_queue_get
    mock_queue_cls = MagicMock(return_value=mock_queue_instance)

    mock_auth_context = DummyAuthContext()

    return {
        "mock_process_cls": mock_process_cls,
        "mock_process": mock_process,
        "mock_queue_cls": mock_queue_cls,
        "mock_queue_instance": mock_queue_instance,
        "fake_httpx_get": fake_httpx_get,
        "mock_auth_context": mock_auth_context,
    }


@patch("schwab_mcp.auth.auth.client_from_received_url")
@patch("schwab_mcp.auth.auth.get_auth_context")
@patch("schwab_mcp.auth.auth.webbrowser")
@patch("schwab_mcp.auth.auth.time")
@patch("schwab_mcp.auth.auth.httpx")
@patch("schwab_mcp.auth.auth.psutil")
@patch("schwab_mcp.auth.QueueType")
@patch("schwab_mcp.auth.ProcessType")
def test_client_from_login_flow_happy_path(
    mock_process_cls: Any,
    mock_queue_cls: Any,
    mock_psutil: Any,
    mock_httpx: Any,
    mock_time: Any,
    mock_webbrowser: Any,
    mock_get_auth_context: Any,
    mock_client_from_received_url: Any,
) -> None:
    """Happy path: server starts, redirect arrives, client returned."""
    mocks = _make_login_flow_mocks(queue_items=["https://127.0.0.1:8182/?code=abc"])

    mock_process_cls.return_value = mocks["mock_process"]
    mock_queue_cls.return_value = mocks["mock_queue_instance"]
    mock_httpx.get.side_effect = mocks["fake_httpx_get"]
    mock_httpx.ConnectError = _httpx.ConnectError
    mock_get_auth_context.return_value = mocks["mock_auth_context"]

    # Make time advance past timeout check: use a large timeout so we don't time out
    call_count: list[int] = [0]

    def fake_time_time() -> float:
        call_count[0] += 1
        # First call: "now" = 0 (sets up timeout_time = 300)
        # Subsequent calls: still 0 so we never hit timeout
        return 0.0

    mock_time.time = fake_time_time
    # Patch the module-level __TIME_TIME used in auth.py
    with patch.object(schwab_auth, "__TIME_TIME", fake_time_time):
        dummy_client = DummyClient()
        mock_client_from_received_url.return_value = dummy_client

        manager = DummyTokenManager(exists=False)
        result = mcp_auth.client_from_login_flow(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            VALID_CALLBACK_URL,
            manager,
            interactive=False,
            callback_timeout=300.0,
        )

    assert result is dummy_client
    mock_client_from_received_url.assert_called_once()
    # Verify the received_url was passed through
    call_kwargs = mock_client_from_received_url.call_args
    assert "https://127.0.0.1:8182/?code=abc" in call_kwargs.args


@patch("schwab_mcp.auth.auth.client_from_received_url")
@patch("schwab_mcp.auth.auth.get_auth_context")
@patch("schwab_mcp.auth.auth.webbrowser")
@patch("schwab_mcp.auth.auth.time")
@patch("schwab_mcp.auth.auth.httpx")
@patch("schwab_mcp.auth.auth.psutil")
@patch("schwab_mcp.auth.QueueType")
@patch("schwab_mcp.auth.ProcessType")
def test_client_from_login_flow_httpx_retry_then_succeeds(
    mock_process_cls: Any,
    mock_queue_cls: Any,
    mock_psutil: Any,
    mock_httpx: Any,
    mock_time: Any,
    mock_webbrowser: Any,
    mock_get_auth_context: Any,
    mock_client_from_received_url: Any,
) -> None:
    """Server readiness polling retries on ConnectError before succeeding."""
    mocks = _make_login_flow_mocks(
        queue_items=["https://127.0.0.1:8182/?code=xyz"],
        httpx_connect_error_count=2,
    )

    mock_process_cls.return_value = mocks["mock_process"]
    mock_queue_cls.return_value = mocks["mock_queue_instance"]
    mock_httpx.get.side_effect = mocks["fake_httpx_get"]
    mock_httpx.ConnectError = _httpx.ConnectError
    mock_get_auth_context.return_value = mocks["mock_auth_context"]

    with patch.object(schwab_auth, "__TIME_TIME", lambda: 0.0):
        dummy_client = DummyClient()
        mock_client_from_received_url.return_value = dummy_client

        manager = DummyTokenManager(exists=False)
        result = mcp_auth.client_from_login_flow(
            FAKE_CLIENT_ID,
            FAKE_CLIENT_SECRET,
            VALID_CALLBACK_URL,
            manager,
            interactive=False,
            callback_timeout=300.0,
        )

    assert result is dummy_client
    # httpx.get was called at least 3 times (2 failures + 1 success)
    assert mock_httpx.get.call_count >= 3


@patch("schwab_mcp.auth.auth.client_from_received_url")
@patch("schwab_mcp.auth.auth.get_auth_context")
@patch("schwab_mcp.auth.auth.webbrowser")
@patch("schwab_mcp.auth.auth.time")
@patch("schwab_mcp.auth.auth.httpx")
@patch("schwab_mcp.auth.auth.psutil")
@patch("schwab_mcp.auth.QueueType")
@patch("schwab_mcp.auth.ProcessType")
def test_client_from_login_flow_times_out(
    mock_process_cls: Any,
    mock_queue_cls: Any,
    mock_psutil: Any,
    mock_httpx: Any,
    mock_time: Any,
    mock_webbrowser: Any,
    mock_get_auth_context: Any,
    mock_client_from_received_url: Any,
) -> None:
    """No redirect received before timeout → RedirectTimeoutError raised."""
    mocks = _make_login_flow_mocks(queue_items=[])  # nothing in queue

    mock_process_cls.return_value = mocks["mock_process"]
    mock_queue_cls.return_value = mocks["mock_queue_instance"]
    mock_httpx.get.return_value = MagicMock()  # server ready immediately
    mock_httpx.ConnectError = _httpx.ConnectError
    mock_get_auth_context.return_value = mocks["mock_auth_context"]

    # Time advances past timeout on the second call inside the wait loop
    time_calls: list[int] = [0]

    def advancing_time() -> float:
        time_calls[0] += 1
        # First call: sets now=0 → timeout_time = now + 1 = 1
        # Second call in loop: returns 2 (> timeout_time) → triggers break
        return float(time_calls[0]) * 2.0

    with patch.object(schwab_auth, "__TIME_TIME", advancing_time):
        manager = DummyTokenManager(exists=False)
        with pytest.raises(schwab_auth.RedirectTimeoutError):
            mcp_auth.client_from_login_flow(
                FAKE_CLIENT_ID,
                FAKE_CLIENT_SECRET,
                VALID_CALLBACK_URL,
                manager,
                interactive=False,
                callback_timeout=1.0,
            )
