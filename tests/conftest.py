from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from click.testing import CliRunner
from schwab.client import AsyncClient

from schwab_mcp import cli
from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabContext, SchwabServerContext


class DummyApprovalManager(ApprovalManager):
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED


class CliFakeAsyncClient:
    """Minimal asynchronous client used by CLI tests."""

    def token_age(self) -> int:
        """Return a fresh token age for CLI tests."""
        return 0

    async def close_async_session(self) -> None:
        """Close the fake client's session without doing any work."""
        return None


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click runner for CLI tests."""
    return CliRunner()


@pytest.fixture
def cli_async_client_type() -> type[CliFakeAsyncClient]:
    """Provide the fake async client type used by CLI tests."""
    return CliFakeAsyncClient


@pytest.fixture
def cli_auth_capture(monkeypatch) -> dict[str, Any]:
    """Patch authentication dependencies and capture their arguments."""
    captured: dict[str, Any] = {}

    class DummyManager:
        """Capture the token path passed to the token manager."""

        def __init__(self, path: str) -> None:
            """Store the token path for assertions."""
            self.path = path
            captured["token_path"] = path

    def fake_easy_client(**kwargs: Any) -> object:
        """Capture easy-client arguments and return a fake client."""
        captured["easy_client_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)
    return captured


@pytest.fixture
def cli_server_capture(monkeypatch) -> dict[str, Any]:
    """Patch server dependencies and capture construction arguments."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(cli, "AsyncClient", CliFakeAsyncClient)

    def fake_easy_client(**kwargs: Any) -> CliFakeAsyncClient:
        """Capture easy-client arguments and return a fake async client."""
        captured["easy_client_called"] = True
        captured["easy_client_kwargs"] = kwargs
        return CliFakeAsyncClient()

    class FakeServer:
        """Capture the server configuration supplied by the CLI."""

        def __init__(
            self,
            name: str,
            client: Any,
            approval_manager: Any,
            *,
            allow_write: bool,
            enable_technical_tools: bool = True,
            use_json: bool = False,
        ) -> None:
            """Record the server constructor arguments."""
            captured["server_name"] = name
            captured["server_client"] = client
            captured["approval_manager"] = approval_manager
            captured["allow_write"] = allow_write
            captured["enable_technical_tools"] = enable_technical_tools
            captured["use_json"] = use_json

        async def run(self) -> None:
            """Record that the server run method was invoked."""
            captured["run_called"] = True

    class DummyManager:
        """Store the token path for server startup tests."""

        def __init__(self, path: str) -> None:
            """Store the token path."""
            self.path = path

    def fake_anyio_run(func: Any, *args: Any, backend: str = "asyncio", **kwargs: Any) -> tuple[Any, ...]:
        """Capture the anyio invocation without starting a server."""
        captured.setdefault("anyio_backend", backend)
        captured.setdefault("anyio_args", args)
        captured.setdefault("anyio_kwargs", kwargs)
        return ()

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)
    monkeypatch.setattr(cli, "SchwabMCPServer", FakeServer)
    monkeypatch.setattr(cli.anyio, "run", fake_anyio_run)
    return captured


@pytest.fixture
def cli_credentials_file(monkeypatch, tmp_path) -> Path:
    """Configure a temporary credentials path with no environment credentials."""
    path = tmp_path / "credentials.yaml"

    def fake_credentials_path(_app: str) -> str:
        """Return the temporary credentials path for the CLI."""
        return str(path)

    monkeypatch.setattr(cli.tokens, "credentials_path", fake_credentials_path)
    monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)
    return path


@pytest.fixture
def cli_credentials_writer(cli_credentials_file) -> Callable[[str, str], Path]:
    """Provide a writer for temporary CLI credential files."""

    def write(client_id: str, client_secret: str) -> Path:
        """Write credentials and return their temporary path."""
        with cli_credentials_file.open("w") as credentials:
            yaml.safe_dump(
                {"client_id": client_id, "client_secret": client_secret},
                credentials,
            )
        return cli_credentials_file

    return write


class _DummySession:
    """Minimal MCP session stub for tests that invoke ctx.warning/log."""

    async def send_log_message(self, **kwargs: Any) -> None:  # noqa: ARG002
        pass


def make_ctx(client: Any) -> SchwabContext:
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, client),
        approval_manager=DummyApprovalManager(),
    )
    request_context = SimpleNamespace(
        lifespan_context=lifespan_context,
        request_id="test-request-id",
        meta=None,
        session=_DummySession(),
    )
    return SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _mcp_server=None,
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def ctx_factory():
    return make_ctx


@pytest.fixture
def fake_call_capture():
    captured: dict[str, Any] = {}

    async def fake_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    return captured, fake_call


@pytest.fixture
def fake_call_factory():
    """Factory fixture for creating fake call mocks with optional return values.

    Returns a factory function that creates (captured_dict, fake_call) tuples.
    The fake_call function captures function calls for test assertions.

    Args:
        return_value: Optional value to return from fake_call (default: "ok")

    Returns:
        Tuple of (captured dict, async fake_call function)
    """

    def factory(return_value: Any = "ok"):
        captured: dict[str, Any] = {}

        async def fake_call(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            captured["kwargs"] = kwargs
            return return_value

        return captured, fake_call

    return factory


class DummyOrderResponse:
    """Mock HTTP response for order placement."""

    def __init__(self, account_hash: str = "default_hash", order_id: int = 123456789):
        self.status_code = 201
        self.url = f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders"
        self.text = ""
        self.content = b""
        self.headers = {"Location": f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/orders/{order_id}"}
        self.is_error = False

    def raise_for_status(self) -> None:
        """No-op method for compatibility with requests.Response."""
        return None


@pytest.fixture
def order_response_factory():
    """Factory fixture for creating DummyOrderResponse instances."""

    def factory(account_hash: str = "default_hash", order_id: int = 123456789):
        return DummyOrderResponse(account_hash=account_hash, order_id=order_id)

    return factory


class DummyPlaceOrderClient:
    """Mock client for place_order() method testing."""

    def __init__(self, order_response: Any):
        self.captured: dict[str, Any] | None = None
        self._response = order_response

    async def place_order(self, *args: Any, **kwargs: Any) -> Any:
        """Capture call arguments and return mock response."""
        self.captured = {"args": args, "kwargs": kwargs}
        return self._response


@pytest.fixture
def place_order_client_factory(order_response_factory):
    """Factory fixture for creating DummyPlaceOrderClient instances."""

    def factory(account_hash: str = "default_hash", order_id: int = 123456789):
        response = order_response_factory(account_hash=account_hash, order_id=order_id)
        return DummyPlaceOrderClient(order_response=response)

    return factory
