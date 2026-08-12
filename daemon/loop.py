"""The daemon's asyncio event loop, shared with background worker threads.

Most daemon work (file downloads, PPTX conversion, transcript polling) happens on
plain threads, but anything that must reach the host browser goes through the
FastAPI WebSocket — i.e. it has to be scheduled back onto the event loop with
``asyncio.run_coroutine_threadsafe``. Those threads have no running loop of their
own, so the loop is captured once at host-server startup and read from here.

This used to live in ``daemon.slides.router`` and was assigned as a SIDE EFFECT of
serving ``/api/slides/check/{slug}``: until some participant happened to open a
slide, ``get_event_loop()`` returned None and every threaded notification was
dropped with "No event loop available" — which is exactly how uploaded files
stopped reaching the host panel.
"""
import asyncio

_loop: asyncio.AbstractEventLoop | None = None


def capture_running_loop() -> None:
    """Record the currently running loop as the daemon's loop. Call at startup."""
    global _loop
    _loop = asyncio.get_running_loop()


def get_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the daemon's FastAPI event loop (None before the host server starts)."""
    return _loop
