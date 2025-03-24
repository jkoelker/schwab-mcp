#

import sys
from typing import Optional

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from schwab.client import AsyncClient

from schwab_mcp import tools


class SchwabMCPServer:
    """
    Schwab Model Context Protocol Server
    """

    def __init__(
        self,
        name: str,
        client: AsyncClient,
        jesus_take_the_wheel: bool = False,
    ):
        self.server = Server(name)
        self.client = client

        # Create registry with automatic tool discovery
        self.registry = tools.Registry(client=client, write=jesus_take_the_wheel)

        # Set up the server
        self._setup_server()

    def _setup_server(self) -> None:
        """Set up the server with tool handlers"""
        self.server.call_tool()(self.call_tool)
        self.server.list_tools()(self.list_tools)

    async def call_tool(
        self, name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        # Get tool instance from registry
        tool = self.registry.get_tool(name)

        # Execute the tool - any exceptions will be caught by the MCP server
        # and converted to a CallToolResult with isError=True
        # Our custom __str__ method in SchwabtoolError ensures the error details are included
        return await tool.execute(arguments)

    async def list_tools(self) -> list[types.Tool]:
        return self.registry.get_tools()

    async def run(self) -> None:
        """Run the server using stdio transport"""
        async with stdio_server() as streams:
            await self.server.run(
                streams[0], streams[1], self.server.create_initialization_options()
            )


def send_error_response(
    error_message: str, code: int = 401, details: Optional[dict] = None
) -> None:
    """
    Send a proper MCP error response to stdout and exit

    This function can be used before the server is started to return
    error responses in the proper MCP format
    """
    if details is None:
        details = {}

    error_data = types.ErrorData(code=code, message=error_message, data=details)

    # Create a JSON-RPC error response
    response = types.JSONRPCError(
        jsonrpc="2.0",
        id="pre-initialization",  # Use a fixed ID for pre-initialization errors
        error=error_data,
    )

    # Serialize and send to stdout
    json_response = response.model_dump_json()
    # Write the response followed by a newline
    sys.stdout.write(f"{json_response}\n")
    sys.stdout.flush()

    # Exit with an error code
    sys.exit(1)
