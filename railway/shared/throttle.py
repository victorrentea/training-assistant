"""Trailing-edge asyncio throttle — coalesces rapid calls into at most one execution per interval."""

import asyncio
import time
from collections.abc import Awaitable
from typing import Callable


class AsyncThrottle:
    """Rate-limit an async callback to at most once per `interval` seconds.

    Trailing-edge: if called during the cooldown, the callback is scheduled
    to run once the interval elapses.  Multiple calls during cooldown are
    coalesced into a single pending execution.
    """

    def __init__(self, interval: float, callback: Callable[[], Awaitable[None]]):
        self._interval = interval
        self._callback = callback
        self._last_run: float = 0.0
        self._pending_handle: asyncio.TimerHandle | None = None

    async def _run_now(self) -> None:
        self._pending_handle = None
        self._last_run = time.monotonic()
        await self._callback()

    def schedule(self) -> None:
        """Request a throttled execution of the callback."""
        elapsed = time.monotonic() - self._last_run
        remaining = self._interval - elapsed
        if remaining <= 0:
            asyncio.ensure_future(self._run_now())
        elif self._pending_handle is None:
            loop = asyncio.get_event_loop()
            self._pending_handle = loop.call_later(
                remaining, lambda: asyncio.ensure_future(self._run_now())
            )
