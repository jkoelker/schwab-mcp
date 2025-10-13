#

from typing import Any


def main(*args: Any, **kwargs: Any):
    """Entry point proxy that defers CLI imports until invocation."""
    from schwab_mcp.cli import main as cli_main

    return cli_main(*args, **kwargs)


__all__ = ["main"]
