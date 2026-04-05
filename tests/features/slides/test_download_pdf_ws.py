"""Unit tests for Railway WS download_pdf handler (railway/features/ws/router.py)."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from railway.shared.state import state
from railway.features.ws.daemon_protocol import MSG_PDF_DOWNLOAD_COMPLETE


def run_async(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_state():
    state.slides_cache_status = {}
    state.daemon_ws = None
    yield
    state.slides_cache_status = {}
    state.daemon_ws = None


def test_download_pdf_sends_complete_ok():
    """_run_download_pdf: download succeeds → push_to_daemon called with status=ok."""
    from railway.features.ws.router import _run_download_pdf

    fake_path = Path("/tmp/slides-cache/x.pdf")

    async def _run():
        with patch("railway.features.slides.cache.do_download",
                   new_callable=AsyncMock, return_value=fake_path) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock) as mock_push:

            await _run_download_pdf("x", "http://example.com/x.pdf")

            mock_download.assert_called_once_with("x", "http://example.com/x.pdf")
            mock_push.assert_called_once_with({
                "type": MSG_PDF_DOWNLOAD_COMPLETE,
                "slug": "x",
                "status": "ok",
            })

    run_async(_run())


def test_download_pdf_sends_complete_error_on_exception():
    """_run_download_pdf: download raises → push_to_daemon called with status=error."""
    from railway.features.ws.router import _run_download_pdf

    async def _run():
        with patch("railway.features.slides.cache.do_download",
                   new_callable=AsyncMock, side_effect=RuntimeError("network failure")) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock) as mock_push:

            await _run_download_pdf("x", "http://example.com/x.pdf")

            assert mock_push.call_count == 1
            call_args = mock_push.call_args[0][0]
            assert call_args["type"] == MSG_PDF_DOWNLOAD_COMPLETE
            assert call_args["slug"] == "x"
            assert call_args["status"] == "error"
            assert "network failure" in call_args["error"]

    run_async(_run())


def test_download_pdf_passes_url_to_do_download():
    """_run_download_pdf passes drive_export_url directly to do_download."""
    from railway.features.ws.router import _run_download_pdf

    fake_path = Path("/tmp/slides-cache/myslug.pdf")

    async def _run():
        with patch("railway.features.slides.cache.do_download",
                   new_callable=AsyncMock, return_value=fake_path) as mock_download, \
             patch("railway.features.ws.router.push_to_daemon",
                   new_callable=AsyncMock):

            await _run_download_pdf("myslug", "https://drive.google.com/export?id=ABC")

            mock_download.assert_called_once_with("myslug", "https://drive.google.com/export?id=ABC")

    run_async(_run())
