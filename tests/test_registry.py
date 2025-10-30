from types import SimpleNamespace
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from schwab.client import AsyncClient

import schwab_mcp.tools as tools_module
from schwab_mcp.tools._registration import register_tool
from schwab_mcp.context import SchwabContext


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

    def register_module(server, *, allow_write: bool) -> None:
        register_tool(server, read_tool)
        register_tool(server, write_tool, write=True)

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
