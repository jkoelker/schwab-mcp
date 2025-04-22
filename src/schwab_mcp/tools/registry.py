#

import inspect
import json
import functools
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    TypeVar,
    get_type_hints,
    get_origin,
    Annotated,
)

import httpx
import mcp.types as types
from authlib.integrations.base_client import OAuthError
from mcp.shared.exceptions import McpError
from schwab.client import AsyncClient

# Type variable for the decorated async function
T = TypeVar("T")


def responsify(
    data: Any,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if isinstance(
        data, (types.TextContent, types.ImageContent, types.EmbeddedResource)
    ):
        return [data]

    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]

    if isinstance(data, list):
        return [responsify(item) for item in data]

    raise ValueError(f"Invalid response type: {type(data)}")


def get_schema_for_type(type_obj: Any, description: str = "") -> dict:
    """Convert a Python type to a JSON schema object"""
    param_schema = {"type": "string"}  # Default

    if type_obj is str:
        param_schema = {"type": "string"}
    elif type_obj is int:
        param_schema = {"type": "integer"}
    elif type_obj is float:
        param_schema = {"type": "number"}
    elif type_obj is bool:
        param_schema = {"type": "boolean"}
    elif get_origin(type_obj) is list:
        param_schema = {"type": "array", "items": {"type": "string"}}

    # Add description if available
    if description:
        param_schema["description"] = description

    return param_schema


class SchwabtoolError(McpError):
    """Custom error class for Schwab MCP Tools"""

    def __str__(self):
        """Custom string representation to include error details"""
        # Include the error data in the string representation
        data = getattr(self, "error", None)

        if data:
            try:
                # Format the error details as JSON
                return f"{self.error.message} - {json.dumps(self.error.data, indent=2)}"
            except Exception:
                # Fallback if JSON serialization fails
                return f"{self.error.message} - {self.error.data}"
        return super().__str__()

    @classmethod
    def auth_error(cls, original_error=None):
        """Create an authentication error response"""
        msg = "Authentication failed. Please run 'schwab-mcp auth' to re-authenticate."
        details = {"original_error": str(original_error)} if original_error else {}
        return cls(types.ErrorData(code=401, message=msg, data=details))

    @classmethod
    def api_error(cls, original_error=None, status_code=None):
        """Create an API error response"""
        msg = "Schwab API error"
        details = {"original_error": str(original_error)} if original_error else {}
        if status_code:
            details["status_code"] = status_code

        # Create an ErrorData object with the details in the data field
        error_data = types.ErrorData(code=500, message=msg, data=details)
        return cls(error_data)

    @classmethod
    def validation_error(cls, message, details=None):
        """Create a validation error response"""
        return cls(types.ErrorData(code=400, message=message, data=details or {}))


class BaseSchwabTool:
    """Base class for Schwab API tools"""

    def __init__(self, client: AsyncClient):
        self.client = client

    def definition(self) -> types.Tool:
        """Return the tool definition - must be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement definition()")

    async def execute(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Execute the tool with the given arguments"""
        raise NotImplementedError("Subclasses must implement execute()")

    @staticmethod
    def handle_api_errors(
        func: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        """Decorator to handle API errors and convert them to McpErrors"""

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except OAuthError as e:
                # Handle authentication errors
                if "refresh_token_authentication_error" in str(e):
                    raise SchwabtoolError.auth_error(e)
                raise SchwabtoolError.api_error(e)
            except httpx.HTTPStatusError as e:
                # Handle HTTP errors
                status_code = e.response.status_code
                error_details = None
                try:
                    # Try to parse response body for more details
                    error_details = e.response.json()
                except Exception:
                    pass

                details = {"status_code": status_code, "original_error": str(e)}

                if error_details:
                    details["error_details"] = error_details

                # Create a more detailed error response
                error_data = types.ErrorData(
                    code=500, message="Schwab API error", data=details
                )
                raise SchwabtoolError(error_data)
            except ValueError as e:
                # Handle validation errors
                raise SchwabtoolError.validation_error(str(e))
            except Exception as e:
                # Handle all other errors
                raise SchwabtoolError.api_error(e)

        return wrapper


class _FunctionTool(BaseSchwabTool):
    """Tool implementation that wraps a function"""

    def __init__(self, client: AsyncClient, func: Callable):
        super().__init__(client)
        self.func = func
        self._client_param = None
        self._definition = self._get_definition()

    def _get_definition(self) -> types.Tool:
        """Create a tool definition from the function's signature"""
        sig = inspect.signature(self.func)
        type_hints = get_type_hints(self.func, include_extras=True)
        doc = inspect.getdoc(self.func) or ""

        # Get function name
        name = self.func.__name__

        # Create properties for the input schema
        properties = {}
        required = []

        # Process each parameter
        for param_name, param in sig.parameters.items():
            # Skip client parameter
            if param.annotation is AsyncClient:
                self._client_param = param_name
                continue

            if param_name == "client" and param.annotation == inspect.Parameter.empty:
                self._client_param = param_name
                continue

            # Track required parameters
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

            # Process parameter type
            if param_name in type_hints:
                param_type = type_hints[param_name]
                description = ""

                # Handle Annotated types
                if get_origin(param_type) is Annotated:
                    description = " ".join(param_type.__metadata__)
                    param_type = param_type.__origin__

                properties[param_name] = get_schema_for_type(param_type, description)

        # Create the input schema
        input_schema = {
            "type": "object",
            "properties": properties,
        }

        if required:
            input_schema["required"] = required

        return types.Tool(
            name=name,
            description=doc,
            inputSchema=input_schema,
        )

    def definition(self) -> types.Tool:
        """Return the cached tool definition"""
        return self._definition

    @BaseSchwabTool.handle_api_errors
    async def execute(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Execute the wrapped function"""
        if self._client_param:
            arguments[self._client_param] = self.client

        return responsify(await self.func(**arguments))


def FunctionTool(func: Callable) -> Callable[AsyncClient, _FunctionTool]:
    """Factory function for creating a FunctionBasedTool"""
    return functools.partial(_FunctionTool, func=func)


@dataclass
class Registry:
    """Registry of available tools with auto-discovery"""

    client: AsyncClient
    write: bool = False
    _tools: List[types.Tool] = field(default_factory=list)
    _instances: Dict[str, BaseSchwabTool] = field(default_factory=dict)

    @classmethod
    def register(cls, tool: Callable[Any, Any] | BaseSchwabTool = None, **kwargs):
        """Class decorator to register a tool class or function for auto-discovery"""
        if not hasattr(cls, "_registered_tools"):
            cls._registered_tools = []

        def _register(tool: Callable[Any, Any] | BaseSchwabTool, write: bool = False):
            if inspect.isfunction(tool):
                wrapped = FunctionTool(tool)
            else:
                wrapped = tool

            wrapped._write = write

            cls._registered_tools.append(wrapped)

            return tool

        if tool is not None and len(kwargs) == 0:
            return _register(tool, write=False)

        def _decorator(func: Callable[Callable[Any, Any] | BaseSchwabTool, Any]):
            return _register(func, **kwargs)

        return _decorator

    def __post_init__(self):
        """Initialize the registry by discovering and registering tools"""
        for tool in getattr(Registry, "_registered_tools", []):
            if getattr(tool, "_write", False) and not self.write:
                continue

            instance = tool(self.client)

            if not isinstance(instance, BaseSchwabTool):
                raise ValueError("Invalid tool class")

            definition = instance.definition()
            self._tools.append(definition)
            self._instances[definition.name] = instance

        if len(self._tools) == 0:
            raise ValueError("No tools registered")

    def get_tools(self) -> list[types.Tool]:
        """Get all registered tools"""
        return self._tools

    def get_tool(self, name: str) -> BaseSchwabTool:
        """Get a tool instance by name"""
        if name not in self._instances:
            raise SchwabtoolError.validation_error(f"Unknown tool: {name}")
        return self._instances[name]

    async def execute_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Execute a tool by name with arguments"""
        tool = self.get_tool(name)
        return await tool.execute(arguments)


# Decorator for registering tool classes or functions
register = Registry.register
