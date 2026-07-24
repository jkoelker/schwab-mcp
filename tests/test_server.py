import asyncio
import io
import json
import logging
import sys
from typing import Any, cast

import pytest
from schwab.client import AsyncClient

from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabServerContext
from schwab_mcp.server import SchwabMCPServer, send_error_response


class DummyApprovalManager(ApprovalManager):
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED


class DummyAsyncClient:
    def __init__(self) -> None:
        self.closed = False
        self.calls = 0

    async def close_async_session(self) -> None:
        self.calls += 1
        self.closed = True


def test_server_configures_client_lifespan() -> None:
    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    approval_manager = DummyApprovalManager()
    server = SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=False,
    )

    lifespan_factory = server._server.settings.lifespan
    assert callable(lifespan_factory)

    async def runner() -> None:
        async with lifespan_factory(server._server) as context:
            assert isinstance(context, SchwabServerContext)
            assert context.client is client
            assert dummy_client.closed is False
            assert approval_manager.started is True

    asyncio.run(runner())
    assert dummy_client.closed is True
    assert dummy_client.calls == 1
    assert approval_manager.stopped is True


def test_server_logs_errors_when_closing_client(caplog) -> None:
    class FailingClient:
        def __init__(self) -> None:
            self.calls = 0

        async def close_async_session(self) -> None:
            self.calls += 1
            raise RuntimeError("boom")

    failing_client = FailingClient()
    client = cast(AsyncClient, failing_client)
    approval_manager = DummyApprovalManager()
    server = SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=True,
    )

    lifespan_factory = server._server.settings.lifespan
    assert callable(lifespan_factory)

    async def runner() -> None:
        async with lifespan_factory(server._server):
            pass

    with caplog.at_level(logging.ERROR):
        asyncio.run(runner())

    assert failing_client.calls == 1
    assert "Failed to close Schwab async client session during shutdown." in caplog.text
    assert approval_manager.started is True
    assert approval_manager.stopped is True


def test_lifespan_logs_error_when_approval_manager_stop_raises(caplog) -> None:
    class FailingApprovalManager(ApprovalManager):
        def __init__(self) -> None:
            self.started = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            raise RuntimeError("approval manager stop boom")

        async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
            return ApprovalDecision.APPROVED

    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    failing_approval = FailingApprovalManager()
    server = SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=failing_approval,
        allow_write=False,
    )

    lifespan_factory = server._server.settings.lifespan
    assert callable(lifespan_factory)

    async def runner() -> None:
        async with lifespan_factory(server._server):
            pass

    with caplog.at_level(logging.ERROR):
        asyncio.run(runner())

    assert failing_approval.started is True
    assert "Failed to shut down approval manager cleanly." in caplog.text
    # Client session close still runs after approval manager failure
    assert dummy_client.closed is True


def test_toon_transform_returns_string_payload_unchanged(monkeypatch) -> None:
    """When use_json=False, the toon transform must pass string payloads through."""
    captured_transform: dict[str, Any] = {}

    import schwab_mcp.server as server_module

    def capturing_register(mcp_server, client, *, result_transform, **kwargs):
        captured_transform["fn"] = result_transform
        # Don't call original — we just want the transform function

    monkeypatch.setattr(server_module, "register_tools", capturing_register)
    monkeypatch.setattr(server_module, "register_resources", lambda *a, **kw: None)

    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    approval_manager = DummyApprovalManager()

    SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=False,
        use_json=False,
    )

    transform = captured_transform["fn"]
    assert transform is not None
    assert transform("already a string") == "already a string"
    # Non-string payload goes through toon encoding (must return a string)
    result = transform({"key": "value"})
    assert isinstance(result, str)


def test_json_strip_transform_returns_string_payload_unchanged(monkeypatch) -> None:
    """When use_json=True, the strip transform must pass string payloads through."""
    captured_transform: dict[str, Any] = {}

    import schwab_mcp.server as server_module

    def capturing_register(mcp_server, client, *, result_transform, **kwargs):
        captured_transform["fn"] = result_transform

    monkeypatch.setattr(server_module, "register_tools", capturing_register)
    monkeypatch.setattr(server_module, "register_resources", lambda *a, **kw: None)

    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    approval_manager = DummyApprovalManager()

    SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=False,
        use_json=True,
    )

    transform = captured_transform["fn"]
    assert transform is not None
    assert transform("already a string") == "already a string"
    # Non-string payload is passed through strip_noise and returned as-is (dict)
    result = transform({"key": "value"})
    assert isinstance(result, dict)


@pytest.mark.anyio
async def test_server_run_calls_run_stdio_async(monkeypatch) -> None:
    """server.run() must delegate to FastMCP's run_stdio_async."""
    called: dict[str, bool] = {}

    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    approval_manager = DummyApprovalManager()
    server = SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=False,
    )

    async def fake_run_stdio_async() -> None:
        called["run"] = True

    monkeypatch.setattr(server._server, "run_stdio_async", fake_run_stdio_async)
    await server.run()
    assert called.get("run") is True


@pytest.mark.anyio
async def test_server_run_http_calls_streamable_http(monkeypatch) -> None:
    """--http path must set host/port and use run_streamable_http_async."""
    called: dict[str, bool] = {}

    dummy_client = DummyAsyncClient()
    client = cast(AsyncClient, dummy_client)
    approval_manager = DummyApprovalManager()
    server = SchwabMCPServer(
        "schwab-mcp",
        client,
        approval_manager=approval_manager,
        allow_write=False,
    )

    async def fake_run_streamable_http_async() -> None:
        called["http"] = True

    monkeypatch.setattr(server._server, "run_streamable_http_async", fake_run_streamable_http_async)
    await server.run(transport="http", host="127.0.0.1", port=3473)
    assert called.get("http") is True
    assert server._server.settings.host == "127.0.0.1"
    assert server._server.settings.port == 3473


def test_send_error_response_defaults_details_to_empty_dict(monkeypatch) -> None:
    """send_error_response without details= uses an empty dict, not None."""
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    with pytest.raises(SystemExit) as exc_info:
        send_error_response("something went wrong", code=401)

    assert exc_info.value.code == 1
    payload = json.loads(buf.getvalue().strip())
    assert payload["error"]["code"] == 401
    assert payload["error"]["message"] == "something went wrong"
    # data should be an empty dict, not null
    assert payload["error"]["data"] == {}
