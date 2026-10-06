"""Leading + trailing-edge throttle for pushes that run on the daemon's asyncio loop.

A conference talk can have 400-500 people join within a minute or two. Pushes of
a whole aggregate (the host roster, the active-participant count) that go out on
every single roster event grow with the square of the audience. A LoopThrottle
turns a burst of requests into at most one run per interval:

* leading edge: the first request after a quiet interval runs immediately, so a
  lone join still shows up at once;
* trailing edge: requests during the cooldown book ONE run at its end. The
  callback reads live state when it runs, so the last change always goes out.

Bookkeeping happens on the event loop thread only. Other threads (the main thread
that drains Railway WS messages) call ``request_threadsafe``.

``railway.shared.throttle.AsyncThrottle`` does not fit here. It must be called on
the loop, and two requests in the same loop tick can both start a run, because
it records the run time only once the run starts.
"""
import asyncio
import time
from collections.abc import Awaitable, Callable

from daemon import log
from daemon.loop import get_event_loop


class LoopThrottle:
    def __init__(self, name: str, interval: float, callback: Callable[[], Awaitable[None]]):
        self._name = name
        self._interval = interval
        self._callback = callback
        self._last_run = float("-inf")
        self._timer: asyncio.TimerHandle | None = None
        self._timer_loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task] = set()

    async def request(self) -> None:
        """Run the callback now (awaited) if the interval has passed, else book a
        trailing run. Call on the event loop thread."""
        if self._claim(asyncio.get_running_loop()):
            await self._run()

    def request_threadsafe(self) -> bool:
        """``request`` from any thread. Returns False, and does nothing, while the
        daemon loop is not running (daemon startup, before the host server is up)."""
        loop = get_event_loop()
        if loop is None or not loop.is_running():
            return False
        loop.call_soon_threadsafe(self._request_on_loop, loop)
        return True

    def reset(self) -> None:
        """Forget past runs and drop a booked trailing run. For tests."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        self._timer_loop = None
        self._last_run = float("-inf")

    def _request_on_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._claim(loop):
            self._spawn(loop)

    def _claim(self, loop: asyncio.AbstractEventLoop) -> bool:
        """True: the caller runs the callback now. False: a trailing run is booked."""
        # A timer booked on another loop belongs to a loop that is gone (tests
        # spin a loop per request), so it would never fire. Book a fresh one.
        if self._timer is not None and self._timer_loop is loop:
            return False
        wait = self._interval - (time.monotonic() - self._last_run)
        if wait <= 0:
            self._last_run = time.monotonic()
            return True
        self._timer = loop.call_later(wait, self._on_timer, loop)
        self._timer_loop = loop
        return False

    def _on_timer(self, loop: asyncio.AbstractEventLoop) -> None:
        self._timer = None
        self._timer_loop = None
        self._last_run = time.monotonic()
        self._spawn(loop)

    def _spawn(self, loop: asyncio.AbstractEventLoop) -> None:
        task = loop.create_task(self._run())
        self._tasks.add(task)  # the loop holds tasks weakly; keep it alive until done
        task.add_done_callback(self._tasks.discard)

    async def _run(self) -> None:
        try:
            await self._callback()
        except Exception as exc:
            log.error("throttle", f"{self._name} push failed: {exc}")
