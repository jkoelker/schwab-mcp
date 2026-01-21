from __future__ import annotations

import logging
import importlib
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

try:
    import pandas_ta_classic as _pandas_ta
except ModuleNotFoundError:
    _pandas_ta = None

pandas_ta = cast(Any, _pandas_ta)


def register(
    server: "FastMCP",
    *,
    allow_write: bool,
    result_transform: Callable[[Any], Any] | None = None,
) -> None:
    """Register optional technical analysis tools if dependencies are available."""
    _ = allow_write

    if _pandas_ta is None:
        logger.debug(
            "Skipping technical analysis tools because pandas_ta_classic is not installed."
        )
        return

    for module in _load_modules():
        register_fn = getattr(module, "register", None)
        if register_fn is None:
            raise AttributeError(
                f"Technical tool module {module.__name__} is missing register()"
            )
        register_fn(
            server,
            allow_write=allow_write,
            result_transform=result_transform,
        )

    logger.debug(
        "Technical analysis tools registered from %s", ", ".join(_MODULE_PATHS)
    )


_MODULE_PATHS: tuple[str, ...] = (
    "schwab_mcp.tools.technical.moving_average",
    "schwab_mcp.tools.technical.momentum",
    "schwab_mcp.tools.technical.trend",
    "schwab_mcp.tools.technical.overlays",
    "schwab_mcp.tools.technical.volatility",
)
_LOADED_MODULES: dict[str, ModuleType] = {}


def _load_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for module_path in _MODULE_PATHS:
        module = _LOADED_MODULES.get(module_path)
        if module is None:
            module = importlib.import_module(module_path)
            _LOADED_MODULES[module_path] = module
        modules.append(module)
    return modules
