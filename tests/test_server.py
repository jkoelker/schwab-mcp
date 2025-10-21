import asyncio
import logging
from typing import cast

from schwab.client import AsyncClient
from schwab_mcp.context import SchwabServerContext
from schwab_mcp.server import SchwabMCPServer
from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest


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
