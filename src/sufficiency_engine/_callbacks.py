"""Safely invoke application-owned synchronous or asynchronous callbacks."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable


async def invoke(callback: Callable[..., object], argument: object, timeout: float) -> object:
    """Run synchronous callbacks off the event-loop thread and await results."""
    async with asyncio.timeout(timeout):
        asynchronous = inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
            type(callback).__call__
        )
        if asynchronous:
            result = callback(argument)
        else:
            result = await asyncio.to_thread(callback, argument)
        if inspect.isawaitable(result):
            return await result
        return result
