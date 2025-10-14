from types import SimpleNamespace
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from schwab.client import AsyncClient

import schwab_mcp.tools as tools_module
from schwab_mcp.tools import registry as tool_registry


def test_register_sets_readonly_annotations() -> None:
    @tool_registry.register()
    async def sample_tool() -> str:
        return "ok"

    annotations = getattr(sample_tool, "_tool_annotations")
    assert isinstance(annotations, ToolAnnotations)
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is None
    assert getattr(sample_tool, "_write") is False
    assert getattr(sample_tool, "_registered_tool") is True


def test_register_sets_write_annotations() -> None:
    @tool_registry.register(write=True)
    async def write_tool() -> str:
        return "ok"

    annotations = getattr(write_tool, "_tool_annotations")
    assert isinstance(annotations, ToolAnnotations)
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert getattr(write_tool, "_write") is True
    assert getattr(write_tool, "_registered_tool") is True


def test_register_tools_uses_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    @tool_registry.register()
    async def read_tool() -> str:
        return "read"

    @tool_registry.register(write=True)
    async def write_tool() -> str:
        return "write"

    read_tool.__doc__ = "read tool"
    write_tool.__doc__ = "write tool"

    dummy_module = SimpleNamespace(read_tool=read_tool, write_tool=write_tool)
    monkeypatch.setattr(tools_module, "_TOOL_MODULES", (dummy_module,))

    class DummyServer:
        def __init__(self) -> None:
            self.tools: list[dict[str, object]] = []

        def add_tool(self, fn, *, name=None, description=None, annotations=None):
            self.tools.append(
                {
                    "fn": fn,
                    "name": name,
                    "description": description,
                    "annotations": annotations,
                }
            )

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
