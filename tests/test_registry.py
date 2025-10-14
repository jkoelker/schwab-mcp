from types import SimpleNamespace
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from schwab.client import AsyncClient

import schwab_mcp.tools as tools_module
from schwab_mcp.tools._registration import register_tool


async def _dummy_tool() -> str:
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


def test_register_tools_respects_allow_write(monkeypatch) -> None:
    async def read_tool() -> str:
        """read tool"""
        return "read"

    async def write_tool() -> str:
        """write tool"""
        return "write"

    def register_module(server, *, allow_write: bool) -> None:
        register_tool(server, read_tool)
        if allow_write:
            register_tool(server, write_tool, write=True)

    dummy_module = SimpleNamespace(register=register_module)
    monkeypatch.setattr(tools_module, "_TOOL_MODULES", (dummy_module,))

    read_only_server = FastMCP(name="read-only")
    tools_module.register_tools(
        read_only_server, cast(AsyncClient, object()), allow_write=False
    )
    read_only_tools = _registered_tools(read_only_server)
    assert [tool.name for tool in read_only_tools] == ["read_tool"]
    assert read_only_tools[0].annotations is not None
    assert read_only_tools[0].annotations.readOnlyHint is True

    write_server = FastMCP(name="read-write")
    tools_module.register_tools(
        write_server, cast(AsyncClient, object()), allow_write=True
    )
    write_tools = {tool.name: tool for tool in _registered_tools(write_server)}
    assert {"read_tool", "write_tool"} == set(write_tools)
    write_annotations = write_tools["write_tool"].annotations
    assert write_annotations is not None
    assert write_annotations.readOnlyHint is False
    assert write_annotations.destructiveHint is True
