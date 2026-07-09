import asyncio
import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Annotated, Any, cast

import pytest
from mcp.server.fastmcp import Context as MCPContext, FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from schwab.client import AsyncClient

import schwab_mcp.tools as tools_module
from schwab_mcp.approvals import ApprovalDecision, ApprovalManager, ApprovalRequest
from schwab_mcp.context import SchwabContext, SchwabServerContext
from schwab_mcp.tools import _registration
from schwab_mcp.tools._registration import (
    _format_argument,
    _is_context_annotation,
    register_tool,
)


async def _dummy_tool(ctx: SchwabContext) -> str:  # noqa: ARG001
    """dummy tool description"""
    return "ok"


def _registered_tools(server: FastMCP) -> list[Tool]:
    manager = getattr(server, "_tool_manager")
    return cast(list[Tool], manager.list_tools())


def _tool_by_name(server: FastMCP, name: str) -> Tool:
    tools = {tool.name: tool for tool in _registered_tools(server)}
    return tools[name]


def test_register_tool_sets_readonly_annotations() -> None:
    server = FastMCP(name="readonly")
    register_tool(server, _dummy_tool)

    tool = _tool_by_name(server, "_dummy_tool")
    annotations = tool.annotations
    assert isinstance(annotations, ToolAnnotations)
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is None
    assert tool.description == (_dummy_tool.__doc__ or "")


def test_register_tool_sets_write_annotations() -> None:
    server = FastMCP(name="write")
    register_tool(server, _dummy_tool, write=True)

    tool = _tool_by_name(server, "_dummy_tool")
    annotations = tool.annotations
    assert isinstance(annotations, ToolAnnotations)
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert tool.description == (_dummy_tool.__doc__ or "")


def test_register_tools_always_registers_write_tools(monkeypatch) -> None:
    async def read_tool(ctx: SchwabContext) -> str:  # noqa: ARG001
        """read tool"""
        return "read"

    async def write_tool(ctx: SchwabContext) -> str:  # noqa: ARG001
        """write tool"""
        return "write"

    def register_module(
        server,
        *,
        allow_write: bool,
        result_transform: Callable[[Any], Any] | None = None,
    ) -> None:
        register_tool(server, read_tool, result_transform=result_transform)
        register_tool(server, write_tool, write=True, result_transform=result_transform)

    dummy_module = SimpleNamespace(register=register_module)
    monkeypatch.setattr(tools_module, "_TOOL_MODULES", (dummy_module,))

    read_only_server = FastMCP(name="read-only")
    tools_module.register_tools(
        read_only_server,
        cast(AsyncClient, object()),
        allow_write=False,
        enable_technical=False,
    )
    read_only_tools = {tool.name: tool for tool in _registered_tools(read_only_server)}
    assert {"read_tool", "write_tool"} == set(read_only_tools)
    assert read_only_tools["write_tool"].annotations is not None
    assert read_only_tools["write_tool"].annotations.readOnlyHint is False

    write_server = FastMCP(name="read-write")
    tools_module.register_tools(
        write_server,
        cast(AsyncClient, object()),
        allow_write=True,
        enable_technical=False,
    )
    write_tools = {tool.name: tool for tool in _registered_tools(write_server)}
    assert {"read_tool", "write_tool"} == set(write_tools)
    write_annotations = write_tools["write_tool"].annotations
    assert write_annotations is not None
    assert write_annotations.readOnlyHint is False
    assert write_annotations.destructiveHint is True


def test_register_tool_applies_result_transform() -> None:
    server = FastMCP(name="transform")

    async def sample_tool() -> dict[str, str]:
        return {"ok": "yes"}

    captured: dict[str, Any] = {}

    def transform(payload: Any) -> str:
        captured["payload"] = payload
        return "encoded"

    register_tool(server, sample_tool, result_transform=transform)
    tool = _tool_by_name(server, "sample_tool")

    async def runner() -> str:
        return await tool.fn()

    result = asyncio.run(runner())
    assert result == "encoded"
    assert captured["payload"] == {"ok": "yes"}


def test_result_transform_handles_sync_tool() -> None:
    """_wrap_result_transform works when the wrapped function returns synchronously."""
    server = FastMCP(name="sync-transform")

    def sync_tool() -> str:  # type: ignore[return-value]
        return "raw"

    register_tool(server, sync_tool, result_transform=str.upper)  # type: ignore[arg-type]
    tool = _tool_by_name(server, "sync_tool")

    async def runner() -> str:
        return await tool.fn()

    result = asyncio.run(runner())
    assert result == "RAW"


def test_result_transform_preserves_strings() -> None:
    server = FastMCP(name="string-transform")

    async def sample_tool() -> str:
        return "already-string"

    captured: dict[str, Any] = {}

    def transform(payload: Any) -> str:
        captured["payload"] = payload
        if isinstance(payload, str):
            return payload
        return "encoded"

    register_tool(server, sample_tool, result_transform=transform)
    tool = _tool_by_name(server, "sample_tool")

    async def runner() -> str:
        return await tool.fn()

    result = asyncio.run(runner())
    assert result == "already-string"
    assert captured["payload"] == "already-string"


# ---------------------------------------------------------------------------
# _is_context_annotation edge cases
# ---------------------------------------------------------------------------


def test_is_context_annotation_none_returns_false() -> None:
    assert _is_context_annotation(None) is False


def test_is_context_annotation_empty_returns_false() -> None:
    assert _is_context_annotation(inspect._empty) is False  # type: ignore[attr-defined]


def test_is_context_annotation_string_schwabcontext_returns_true() -> None:
    assert _is_context_annotation("SchwabContext") is True


def test_is_context_annotation_other_string_returns_false() -> None:
    assert _is_context_annotation("str") is False


def test_is_context_annotation_annotated_type_returns_true() -> None:
    annotated = Annotated[SchwabContext, "the mcp context"]
    assert _is_context_annotation(annotated) is True


def test_is_context_annotation_union_containing_context_returns_true() -> None:
    union = SchwabContext | None
    assert _is_context_annotation(union) is True


def test_is_context_annotation_union_without_context_returns_false() -> None:
    union = str | int
    assert _is_context_annotation(union) is False


def test_is_context_annotation_unrelated_type_returns_false() -> None:
    assert _is_context_annotation(int) is False


def test_is_context_annotation_generic_with_other_origin_returns_false() -> None:
    # list[str] has a non-Annotated, non-Union origin → falls through to False
    assert _is_context_annotation(list[str]) is False


# ---------------------------------------------------------------------------
# _format_argument truncation
# ---------------------------------------------------------------------------


def test_format_argument_truncates_long_values() -> None:
    long_str = "x" * 300
    result = _format_argument(long_str)
    assert len(result) <= 256
    assert result.endswith("...")


def test_format_argument_short_values_unchanged() -> None:
    result = _format_argument("hello")
    assert result == repr("hello")


# ---------------------------------------------------------------------------
# _ensure_schwab_context: MCPContext conversion and invalid-type guard
# ---------------------------------------------------------------------------


class _DummyApprovalManager(ApprovalManager):
    async def require(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.APPROVED


def _make_request_context() -> Any:
    lifespan_context = SchwabServerContext(
        client=cast(AsyncClient, object()),
        approval_manager=_DummyApprovalManager(),
    )
    return SimpleNamespace(
        lifespan_context=lifespan_context,
        request_id="test-req",
        meta=None,
        session=SimpleNamespace(send_log_message=lambda **_: None),
    )


def test_ensure_schwab_context_converts_mcp_context() -> None:
    """An MCPContext argument is transparently converted to SchwabContext."""
    request_context = _make_request_context()

    received: list[Any] = []

    async def tool(ctx: SchwabContext) -> str:
        received.append(ctx)
        return "ok"

    wrapped = _registration._ensure_schwab_context(tool)

    base_ctx = MCPContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )

    async def runner() -> str:
        return await wrapped(base_ctx)

    asyncio.run(runner())
    assert len(received) == 1
    assert isinstance(received[0], SchwabContext)


def test_ensure_schwab_context_rejects_invalid_type() -> None:
    """A non-context argument raises TypeError."""

    async def tool(ctx: SchwabContext) -> str:
        return "ok"

    wrapped = _registration._ensure_schwab_context(tool)

    async def runner() -> None:
        await wrapped("not-a-context")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="must be an MCP context"):
        asyncio.run(runner())


def test_ensure_schwab_context_handles_sync_result() -> None:
    """Works when the wrapped function returns a non-awaitable synchronously."""

    def sync_tool(ctx: SchwabContext) -> str:  # type: ignore[return-value]
        return "sync"

    wrapped = _registration._ensure_schwab_context(sync_tool)  # type: ignore[arg-type]
    request_context = _make_request_context()
    ctx = SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )

    async def runner() -> Any:
        return await wrapped(ctx)

    result = asyncio.run(runner())
    assert result == "sync"


# ---------------------------------------------------------------------------
# register_tool: annotation backfill from partial ToolAnnotations
# ---------------------------------------------------------------------------


async def _noop_tool(ctx: SchwabContext) -> str:  # noqa: ARG001
    """noop"""
    return "ok"


def test_register_tool_fills_readonly_hint_when_missing() -> None:
    """readOnlyHint=None in caller-supplied annotations is filled based on write flag."""
    server = FastMCP(name="hint-test")
    partial_annotations = ToolAnnotations(readOnlyHint=None, destructiveHint=None)
    register_tool(server, _noop_tool, annotations=partial_annotations)

    tool = _tool_by_name(server, "_noop_tool")
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True  # non-write tool → True


def test_register_tool_fills_destructive_hint_for_write_tools() -> None:
    """destructiveHint=None is filled to True for write tools."""
    server = FastMCP(name="destructive-test")
    partial_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=None)
    register_tool(server, _noop_tool, write=True, annotations=partial_annotations)

    tool = _tool_by_name(server, "_noop_tool")
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True


def test_register_tool_preserves_explicit_annotation_values() -> None:
    """Explicitly set annotation values are not overwritten."""
    server = FastMCP(name="explicit-test")
    explicit_annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    register_tool(server, _noop_tool, write=True, annotations=explicit_annotations)

    tool = _tool_by_name(server, "_noop_tool")
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False


# ---------------------------------------------------------------------------
# Forward-ref globals: integration test that covers globals-copy call sites
# ---------------------------------------------------------------------------


def test_wrapped_tool_resolves_forward_ref_annotations() -> None:
    """A tool using forward-ref annotations from its own module executes without NameError."""

    # Define a tool at module scope so its __module__ resolves correctly,
    # then register it through the full stack (ensure + wrap + result_transform).
    # All three wrappers copy the originating module's globals into the wrapper,
    # ensuring forward-ref annotations remain resolvable.

    async def annotated_tool(ctx: "SchwabContext") -> "str":  # noqa: F821
        return "forward-ref-ok"

    annotated_tool.__module__ = __name__

    server = FastMCP(name="fwd-ref")
    register_tool(server, annotated_tool, result_transform=lambda v: v)

    tool = _tool_by_name(server, "annotated_tool")

    request_context = _make_request_context()
    ctx = SchwabContext.model_construct(
        _request_context=cast(Any, request_context),
        _fastmcp=None,
    )

    result = asyncio.run(tool.fn(ctx))
    assert result == "forward-ref-ok"
