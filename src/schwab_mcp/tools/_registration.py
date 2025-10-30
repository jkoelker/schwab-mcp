from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
import functools
import inspect
import logging
import sys
import types
import uuid
from typing import Annotated, Any, Union, cast, get_args, get_origin, get_type_hints

from mcp.server.fastmcp import FastMCP, Context as MCPContext
from mcp.types import ToolAnnotations
from schwab_mcp.context import SchwabContext
from schwab_mcp.approvals import ApprovalDecision, ApprovalRequest


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
                    _fastmcp=getattr(value, "_fastmcp", None),
                )
            else:
                raise TypeError(
                    f"Argument '{name}' must be an MCP context, got {type(value)!r}"
                )

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


def _wrap_with_approval(func: ToolFn) -> ToolFn:
    signature, ctx_params = _resolve_context_parameters(func)
    if not ctx_params:
        raise TypeError(
            f"Write tool '{func.__name__}' must accept a SchwabContext parameter for approval gating."
        )

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
                    _fastmcp=getattr(value, "_fastmcp", None),
                )
                bound.arguments[name] = converted
                context = converted
                continue

        if context is None:
            raise RuntimeError(
                f"Write tool '{func.__name__}' missing SchwabContext during invocation."
            )

        arguments = {
            name: _format_argument(arg)
            for name, arg in bound.arguments.items()
            if name not in ctx_params
        }

        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            tool_name=func.__name__,
            request_id=context.request_id,
            client_id=context.client_id,
            arguments=arguments,
        )

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
        await context.warning(message)

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


async def _report_approval_completion(
    context: SchwabContext, decision: ApprovalDecision
) -> None:
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
        progress_token = getattr(context.request_context.meta, "progressToken", None)
    except ValueError:
        return False
    return bool(progress_token)


def register_tool(
    server: FastMCP,
    func: ToolFn,
    *,
    write: bool = False,
    annotations: ToolAnnotations | None = None,
) -> None:
    """Register a Schwab tool using FastMCP's decorator plumbing."""

    func = _ensure_schwab_context(func)
    if write:
        func = _wrap_with_approval(func)

    tool_annotations = annotations
    if tool_annotations is None:
        if write:
            tool_annotations = ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
            )
        else:
            tool_annotations = ToolAnnotations(
                readOnlyHint=True,
            )
    else:
        update: dict[str, Any] = {}
        if tool_annotations.readOnlyHint is None:
            update["readOnlyHint"] = not write
        if write and tool_annotations.destructiveHint is None:
            update["destructiveHint"] = True
        if update:
            tool_annotations = tool_annotations.model_copy(update=update)

    server.tool(
        name=func.__name__,
        description=func.__doc__,
        annotations=tool_annotations,
    )(func)


__all__ = ["register_tool"]
