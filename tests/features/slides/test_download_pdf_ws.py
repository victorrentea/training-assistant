"""Unit tests for Railway WS download_pdf handler (railway/features/ws/router.py)."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from railway.shared.state import state
from railway.features.ws.daemon_protocol import MSG_PDF_DOWNLOAD_COMPLETE


def run_async(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_state():
    state.slides_catalog = {}
    state.slides_cache_status = {}
    state.slides_gdrive_locks = {}
    state.slides_download_events = {}
    state.slides_download_semaphore = asyncio.Semaphore(3)
    state.daemon_ws = None
    yield
    state.slides_catalog = {}
    state.slides_cache_status = {}
    state.slides_gdrive_locks = {}
    state.slides_download_events = {}
    state.slides_download_semaphore = asyncio.Semaphore(3)
    state.daemon_ws = None


def test_download_pdf_sends_complete_ok():
    """_run_download_pdf: download succeeds → push_to_daemon called with status=ok."""
    from railway.features.ws.router import _run_download_pdf

    fake_path = Path("/tmp/slides-cache/x.pdf")

    async def _run():
        with patch("railway.features.slides.cache.download_or_wait_cached",
                   new_callable=AsyncMock, return_value=fake_path) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock) as mock_push:

            state.slides_catalog["x"] = {"drive_export_url": "http://example.com/x.pdf"}
            await _run_download_pdf("x", "http://example.com/x.pdf")

            mock_push.assert_called_once_with({
                "type": MSG_PDF_DOWNLOAD_COMPLETE,
                "slug": "x",
                "status": "ok",
            })

    run_async(_run())


def test_download_pdf_sends_complete_error_on_none():
    """_run_download_pdf: download returns None → push_to_daemon called with status=error."""
    from railway.features.ws.router import _run_download_pdf

    async def _run():
        with patch("railway.features.slides.cache.download_or_wait_cached",
                   new_callable=AsyncMock, return_value=None) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock) as mock_push:

            state.slides_catalog["x"] = {"drive_export_url": "http://example.com/x.pdf"}
            await _run_download_pdf("x", "http://example.com/x.pdf")

            assert mock_push.call_count == 1
            call_args = mock_push.call_args[0][0]
            assert call_args["type"] == MSG_PDF_DOWNLOAD_COMPLETE
            assert call_args["slug"] == "x"
            assert call_args["status"] == "error"

    run_async(_run())


def test_download_pdf_deduplication():
    """Two _run_download_pdf calls for the same slug: both succeed and push status=ok.

    download_or_wait_cached uses the per-slug asyncio.Lock so the second call waits
    on the lock and then returns the cached file immediately. Both callers independently
    call download_or_wait_cached, but the actual HTTP download happens only once (inside
    the cache module). Here we verify that both _run_download_pdf tasks push status=ok.
    """
    from railway.features.ws.router import _run_download_pdf

    fake_path = Path("/tmp/slides-cache/myslug.pdf")
    download_call_count = [0]

    async def slow_download_or_wait(slug: str) -> Path:
        download_call_count[0] += 1
        # Simulate a slow download on first call
        if download_call_count[0] == 1:
            await asyncio.sleep(0.05)
        return fake_path

    async def _run():
        with patch("railway.features.slides.cache.download_or_wait_cached",
                   side_effect=slow_download_or_wait) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock) as mock_push:

            state.slides_catalog["myslug"] = {"drive_export_url": "http://example.com/myslug.pdf"}

            # Fire two concurrent download tasks
            task1 = asyncio.create_task(_run_download_pdf("myslug", "http://example.com/myslug.pdf"))
            task2 = asyncio.create_task(_run_download_pdf("myslug", "http://example.com/myslug.pdf"))
            await asyncio.gather(task1, task2)

            # Both tasks pushed a completion notification
            assert mock_push.call_count == 2
            # Both should have status ok (fake returns fake_path for both)
            statuses = [c[0][0]["status"] for c in mock_push.call_args_list]
            assert all(s == "ok" for s in statuses), f"Expected all ok, got {statuses}"

    run_async(_run())
