import pytest
from mcp.types import ToolAnnotations
from mcp.server.fastmcp import FastMCP
from schwab.client import AsyncClient
from typing import cast

import schwab_mcp.tools as tools_module
from schwab_mcp.tools import registry as tool_registry
from schwab_mcp.tools import utils as tool_utils


def _pop_registered(count_before: int) -> None:
    """Helper to remove any tools appended during a test."""
    while len(tool_registry._REGISTERED_TOOLS) > count_before:
        tool_registry._REGISTERED_TOOLS.pop()


def test_register_sets_readonly_annotations() -> None:
    count_before = len(tool_registry._REGISTERED_TOOLS)

    async def sample_tool() -> str:
        return "ok"

    registered = tool_registry.register(sample_tool)
    try:
        annotations = getattr(registered, "_tool_annotations")
        assert isinstance(annotations, ToolAnnotations)
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is None
        assert getattr(registered, "_write") is False
    finally:
        _pop_registered(count_before)


def test_register_sets_write_annotations() -> None:
    count_before = len(tool_registry._REGISTERED_TOOLS)

    async def write_tool() -> str:
        return "ok"

    registered = tool_registry.register(write_tool, write=True)
    try:
        annotations = getattr(registered, "_tool_annotations")
        assert isinstance(annotations, ToolAnnotations)
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is True
        assert getattr(registered, "_write") is True
    finally:
        _pop_registered(count_before)


def test_register_tools_uses_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def read_tool() -> str:
        return "read"

    async def write_tool() -> str:
        return "write"

    read_annotations = ToolAnnotations(readOnlyHint=True)
    write_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

    setattr(read_tool, "__doc__", "read tool")
    setattr(write_tool, "__doc__", "write tool")
    setattr(read_tool, "_write", False)
    setattr(write_tool, "_write", True)
    setattr(read_tool, "_tool_annotations", read_annotations)
    setattr(write_tool, "_tool_annotations", write_annotations)

    monkeypatch.setattr(
        tools_module,
        "iter_registered_tools",
        lambda: [read_tool, write_tool],
    )

    class DummyServer:
        def __init__(self) -> None:
            self.tools: list[dict[str, object]] = []

        def tool(self, *, name=None, description=None, annotations=None):
            def decorator(fn):
                self.tools.append(
                    {
                        "fn": fn,
                        "name": name,
                        "description": description,
                        "annotations": annotations,
                    }
                )
                return fn

            return decorator

    dummy_client = object()

    server_read_only = DummyServer()
    tools_module.register_tools(
        cast(FastMCP, server_read_only),
        cast(AsyncClient, dummy_client),
        allow_write=False,
    )

    assert [entry["fn"] for entry in server_read_only.tools] == [read_tool]
    read_entry = server_read_only.tools[0]
    assert isinstance(read_entry["annotations"], ToolAnnotations)
    assert read_entry["annotations"].readOnlyHint is True

    server_read_write = DummyServer()
    tools_module.register_tools(
        cast(FastMCP, server_read_write),
        cast(AsyncClient, dummy_client),
        allow_write=True,
    )

    registered_functions = {entry["fn"] for entry in server_read_write.tools}
    assert registered_functions == {read_tool, write_tool}

    write_entry = next(
        entry for entry in server_read_write.tools if entry["fn"] is write_tool
    )
    assert isinstance(write_entry["annotations"], ToolAnnotations)
    assert write_entry["annotations"].readOnlyHint is False
    assert write_entry["annotations"].destructiveHint is True

    # Reset write access flag for other tests
    tool_utils.set_write_enabled(False)
