from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import sys
import types
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Annotated, Any, Union, cast, get_args, get_origin, get_type_hints

from mcp.server.mcpserver import Context as MCPContext, MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, ValidationError

from schwab_mcp.approvals import ApprovalDecision, ApprovalRequest
from schwab_mcp.context import SchwabContext

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[Any]]

_APPROVAL_PROGRESS_INTERVAL = 5.0
_APPROVAL_WAIT_MESSAGE = "Waiting for reviewer approval…"


def _is_context_annotation(annotation: Any) -> bool:
    if annotation in (inspect._empty, None):
        return False
    if annotation is SchwabContext:
        return True
    if annotation == "SchwabContext":
        return True
    if isinstance(annotation, str):
        return annotation == "SchwabContext"

    origin = get_origin(annotation)
    if origin is None:
        return False

    if origin in (Annotated,):
        args = get_args(annotation)
        return bool(args) and _is_context_annotation(args[0])

    if origin in (Union, types.UnionType):
        return any(_is_context_annotation(arg) for arg in get_args(annotation))

    return False


def _resolve_context_parameters(func: ToolFn) -> tuple[inspect.Signature, list[str]]:
    signature = inspect.signature(func)

    module = sys.modules.get(func.__module__)
    globalns = vars(module) if module else {}

    type_hints: dict[str, Any]
    try:
        type_hints = get_type_hints(func, globalns=globalns, include_extras=True)
    except TypeError:
        type_hints = get_type_hints(func, globalns=globalns)
    except Exception:
        type_hints = {}

    ctx_params = []
    for name, param in signature.parameters.items():
        annotation = type_hints.get(name, param.annotation)
        if _is_context_annotation(annotation):
            ctx_params.append(name)

    return signature, ctx_params


def _ensure_schwab_context(func: ToolFn) -> ToolFn:
    signature, ctx_params = _resolve_context_parameters(func)
    if not ctx_params:
        return func

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind_partial(*args, **kwargs)
        for name in ctx_params:
            if name not in bound.arguments:
                continue
            value = bound.arguments[name]
            if isinstance(value, SchwabContext):
                continue
            if isinstance(value, MCPContext):
                bound.arguments[name] = SchwabContext.model_construct(
                    _request_context=value.request_context,
                    _mcp_server=getattr(value, "_mcp_server", None),
                )
            else:
                raise TypeError(f"Argument '{name}' must be an MCP context, got {type(value)!r}")

        result = func(*bound.args, **bound.kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    # Ensure annotations referencing names from the original module remain resolvable.
    wrapper_globals = cast(dict[str, Any], getattr(wrapper, "__globals__", {}))
    module = inspect.getmodule(func)
    if module is not None:
        module_globals = vars(module)
        if wrapper_globals is not module_globals:
            for key, value in module_globals.items():
                wrapper_globals.setdefault(key, value)

    return wrapper


def _format_argument(value: Any) -> str:
    text = repr(value)
    if len(text) > 256:
        return f"{text[:253]}..."
    return text


async def run_approval(context: SchwabContext, request: ApprovalRequest) -> ApprovalDecision:
    """Run an approval request through progress reporting and the configured
    :class:`ApprovalManager`, returning the resulting decision.

    Shared by the automatic write-tool approval wrapping below and by tools
    that need to build their own :class:`ApprovalRequest` (e.g. to surface
    resolved state rather than raw call arguments to the reviewer).
    """
    if _has_progress_token(context):
        await context.report_progress(0, 1, _APPROVAL_WAIT_MESSAGE)
    keepalive_task = _start_approval_keepalive(context)

    try:
        decision = await context.approvals.require(request)
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
            with suppress(asyncio.CancelledError):
                await keepalive_task

    await _report_approval_completion(context, decision)
    return decision


def _wrap_with_approval(func: ToolFn) -> ToolFn:
    signature, ctx_params = _resolve_context_parameters(func)
    if not ctx_params:
        raise TypeError(f"Write tool '{func.__name__}' must accept a SchwabContext parameter for approval gating.")

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind_partial(*args, **kwargs)
        context: SchwabContext | None = None

        for name in ctx_params:
            if name not in bound.arguments:
                continue

            value = bound.arguments[name]

            if isinstance(value, SchwabContext):
                context = value
                continue

            if isinstance(value, MCPContext):
                converted = SchwabContext.model_construct(
                    _request_context=value.request_context,
                    _mcp_server=getattr(value, "_mcp_server", None),
                )
                bound.arguments[name] = converted
                context = converted
                continue

        if context is None:
            raise RuntimeError(f"Write tool '{func.__name__}' missing SchwabContext during invocation.")

        arguments = {name: _format_argument(arg) for name, arg in bound.arguments.items() if name not in ctx_params}

        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            tool_name=func.__name__,
            request_id=context.request_id,
            client_id=context.client_id,
            arguments=arguments,
        )

        decision = await run_approval(context, request)
        logger.info(
            "Approval decision %s for tool '%s' (approval_id=%s, client_id=%s, request_id=%s)",
            decision.value,
            func.__name__,
            request.id,
            request.client_id or "<unknown>",
            request.request_id,
        )
        if decision is ApprovalDecision.APPROVED:
            result = func(*bound.args, **bound.kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        message = (
            f"Write operation for tool '{func.__name__}' denied by reviewer."
            if decision is ApprovalDecision.DENIED
            else f"Approval request for tool '{func.__name__}' expired."
        )
        logger.warning(message)

        if decision is ApprovalDecision.DENIED:
            raise PermissionError(message)
        raise TimeoutError(message)

    wrapper_globals = cast(dict[str, Any], getattr(wrapper, "__globals__", {}))
    module = inspect.getmodule(func)
    if module is not None:
        module_globals = vars(module)
        if wrapper_globals is not module_globals:
            for key, value in module_globals.items():
                wrapper_globals.setdefault(key, value)

    return wrapper


def _start_approval_keepalive(context: SchwabContext) -> asyncio.Task[None] | None:
    if not _has_progress_token(context):
        return None

    async def _keepalive() -> None:
        elapsed = 0.0
        try:
            while True:
                await asyncio.sleep(_APPROVAL_PROGRESS_INTERVAL)
                elapsed_line = int(elapsed + _APPROVAL_PROGRESS_INTERVAL)
                await context.report_progress(
                    0,
                    1,
                    f"{_APPROVAL_WAIT_MESSAGE} ({elapsed_line}s elapsed)",
                )
                elapsed += _APPROVAL_PROGRESS_INTERVAL
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - best effort keepalive
            logger.debug("Failed to send approval progress keepalive", exc_info=True)

    return asyncio.create_task(_keepalive())


async def _report_approval_completion(context: SchwabContext, decision: ApprovalDecision) -> None:
    if not _has_progress_token(context):
        return

    message = (
        "Reviewer approved the request."
        if decision is ApprovalDecision.APPROVED
        else "Approval flow finished without approval."
    )
    try:
        await context.report_progress(1, 1, message)
    except Exception:  # pragma: no cover - best effort completion
        logger.debug("Failed to send approval completion progress", exc_info=True)


def _has_progress_token(context: SchwabContext) -> bool:
    try:
        meta = context.request_context.meta
    except ValueError:
        return False
    return bool(meta.get("progress_token")) if meta else False


def _wrap_result_transform(func: ToolFn, transform: Callable[[Any], Any]) -> ToolFn:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return transform(result)

    # Preserve global namespace similar to other wrappers
    wrapper_globals = cast(dict[str, Any], getattr(wrapper, "__globals__", {}))
    module = inspect.getmodule(func)
    if module is not None:
        module_globals = vars(module)
        if wrapper_globals is not module_globals:
            for key, value in module_globals.items():
                wrapper_globals.setdefault(key, value)

    return cast(ToolFn, wrapper)


def _forbid_unknown_arguments(server: MCPServer, name: str) -> None:
    """Make the registered tool ``name`` refuse unknown top-level arguments.

    MCPServer builds each tool's argument model with pydantic's default of
    ignoring extra keys, so a misnamed argument (``stop_loss`` for
    ``loss_price``) would be dropped and the call would run without it. This
    swaps in a subclass with ``extra="forbid"``, so such a call is refused
    before conversion or execution, and advertises the closed schema. The SDK
    reads ``fn_metadata.arg_model`` on every call, so the swap takes effect at
    once. Registration fails rather than leaving a tool open if the SDK no
    longer exposes what this relies on.
    """
    tool = server._tool_manager.get_tool(name)
    if tool is None:
        raise RuntimeError(f"Tool {name!r} was not registered; cannot close its argument model")
    base: type[ArgModelBase] = tool.fn_metadata.arg_model
    closed = cast(
        type[ArgModelBase],
        types.new_class(
            base.__name__,
            (base,),
            exec_body=lambda ns: ns.update(__module__=base.__module__, model_config=ConfigDict(extra="forbid")),
        ),
    )
    tool.fn_metadata.arg_model = closed
    tool.parameters = closed.model_json_schema(by_alias=True)


_UNKNOWN_ARGUMENT_PROBE = "schwab_mcp_unknown_argument_probe"


def verify_closed_arguments(server: MCPServer) -> None:
    """Refuse to start if any registered tool accepts unknown top-level arguments.

    Probes each tool's real validator with an unknown key and checks that the
    published schema says ``additionalProperties: false``. This catches a tool
    registered around :func:`register_tool` and an SDK change that would make
    :func:`_forbid_unknown_arguments` silently stop working.
    """
    open_tools: list[str] = []
    for tool in server._tool_manager.list_tools():
        try:
            tool.fn_metadata.validate_arguments({_UNKNOWN_ARGUMENT_PROBE: None})
        except ValidationError as exc:
            refused = any(error["type"] == "extra_forbidden" for error in exc.errors())
            if refused and tool.parameters.get("additionalProperties") is False:
                continue
        open_tools.append(tool.name)
    if open_tools:
        raise RuntimeError(f"Refusing to start: these tools accept unknown arguments: {', '.join(sorted(open_tools))}")


def register_tool(
    server: MCPServer,
    func: ToolFn,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register a Schwab tool using MCPServer's decorator plumbing."""
    func = _ensure_schwab_context(func)
    if write:
        func = _wrap_with_approval(func)
    if result_transform is not None:
        func = _wrap_result_transform(func, result_transform)

    tool_annotations = annotations
    if tool_annotations is None:
        if write:
            tool_annotations = ToolAnnotations(
                read_only_hint=False,
                destructive_hint=True,
            )
        else:
            tool_annotations = ToolAnnotations(
                read_only_hint=True,
            )
    else:
        update: dict[str, Any] = {}
        if tool_annotations.read_only_hint is None:
            update["read_only_hint"] = not write
        if write and tool_annotations.destructive_hint is None:
            update["destructive_hint"] = True
        if update:
            tool_annotations = tool_annotations.model_copy(update=update)

    server.tool(
        name=func.__name__,
        description=func.__doc__,
        annotations=tool_annotations,
    )(func)
    _forbid_unknown_arguments(server, func.__name__)


__all__ = ["register_tool", "run_approval", "verify_closed_arguments"]
