#

from typing import Callable


async def call(func: Callable, *args, **kwargs):
    """Call a method on the Schwab client"""
    response = await func(*args, **kwargs)
    response.raise_for_status()
    return response.text
