"""
Unit tests for features/slides/cache.py

Tests the server-side PDF cache logic: PDF download and do_download flow.
"""
import asyncio
import hashlib
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from railway.shared.state import state


def _reset_state():
    """Reset all slides-cache-related state fields to clean values."""
    state.slides_cache_status = {}
    state.daemon_ws = None


def run_async(coro):
    """Run an async coroutine in a new event loop (for sync test methods)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(data: bytes, headers: dict | None = None):
    """Create a mock HTTP response object usable as a context manager."""
    resp = MagicMock()
    resp.read.return_value = data
    mock_headers = MagicMock()
    _headers = headers or {}
    mock_headers.get = lambda key, default="": _headers.get(key, default)
    resp.headers = mock_headers
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _make_http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="http://example.com", code=code, msg="error", hdrs={}, fp=None)


# ---------------------------------------------------------------------------
# _download_pdf_sync tests
# ---------------------------------------------------------------------------

class TestDownloadPdfSync(unittest.TestCase):

    def test_download_pdf_saves_file(self):
        """Valid PDF data is written to the destination file."""
        from railway.features.slides.cache import _download_pdf_sync

        pdf_content = b"%PDF-1.4 test content for download"
        resp = _make_http_response(pdf_content)

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "test.pdf"
            with patch("urllib.request.urlopen", return_value=resp):
                size = _download_pdf_sync("https://example.com/test.pdf", dest)

            assert dest.exists()
            assert dest.read_bytes() == pdf_content
            assert size == len(pdf_content)

    def test_download_pdf_rejects_non_pdf(self):
        """Content not starting with %PDF raises RuntimeError."""
        from railway.features.slides.cache import _download_pdf_sync

        html_content = b"<html><body>Not a PDF</body></html>"
        resp = _make_http_response(html_content)

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "bad.pdf"
            with patch("urllib.request.urlopen", return_value=resp):
                with pytest.raises(RuntimeError, match="%PDF"):
                    _download_pdf_sync("https://example.com/bad.pdf", dest)

            # File should NOT be written
            assert not dest.exists()

    def test_download_pdf_creates_parent_dirs(self):
        """download_pdf_sync creates missing parent directories."""
        from railway.features.slides.cache import _download_pdf_sync

        pdf_content = b"%PDF-1.4 nested dir test"
        resp = _make_http_response(pdf_content)

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "a" / "b" / "c" / "test.pdf"
            with patch("urllib.request.urlopen", return_value=resp):
                size = _download_pdf_sync("https://example.com/test.pdf", dest)

            assert dest.exists()
            assert size == len(pdf_content)


# ---------------------------------------------------------------------------
# do_download tests
# ---------------------------------------------------------------------------

class TestDoDownload(unittest.TestCase):

    def test_do_download_success(self):
        """do_download downloads, updates status to 'cached', and returns path."""
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            pdf_data = b"%PDF-1.4 do_download test"

            def _mock_download(url_, dest_):
                dest_.parent.mkdir(parents=True, exist_ok=True)
                dest_.write_bytes(pdf_data)
                return len(pdf_data)

            async def _run():
                _reset_state()
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch.object(cache_mod, "_download_pdf_sync", side_effect=_mock_download),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    return await cache_mod.do_download("my-deck", "https://example.com/my-deck.pdf")

            result = run_async(_run())

        assert result == cache_dir / "my-deck.pdf"
        assert state.slides_cache_status["my-deck"]["status"] == "cached"

    def test_do_download_failure_updates_status(self):
        """do_download sets status to 'download_failed' and re-raises on failure."""
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            async def _run():
                _reset_state()
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch.object(cache_mod, "_download_pdf_sync", side_effect=RuntimeError("network error")),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    with pytest.raises(RuntimeError, match="network error"):
                        await cache_mod.do_download("bad-deck", "https://example.com/bad.pdf")

            run_async(_run())

        assert state.slides_cache_status["bad-deck"]["status"] == "download_failed"
