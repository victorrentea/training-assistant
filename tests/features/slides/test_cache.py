"""
Unit tests for features/slides/cache.py

Tests the server-side PDF cache logic: fingerprint probing, PDF download,
concurrent request deduplication, and catalog management.
"""
import asyncio
import hashlib
import io
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Import state singleton first so we can manipulate it in tests
from railway.shared.state import state


def _reset_state():
    """Reset all slides-cache-related state fields to clean values."""
    state.slides_catalog = {}
    state.slides_cache_status = {}
    state.slides_download_events = {}
    state.slides_gdrive_locks = {}
    state.slides_fingerprints = {}
    state.slides_download_semaphore = asyncio.Semaphore(3)
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
# _probe_fingerprint_sync tests
# ---------------------------------------------------------------------------

class TestProbeFingerprintSync(unittest.TestCase):

    def test_probe_fingerprint_uses_head(self):
        """HEAD returns ETag → fingerprint is 'hdr:...' format."""
        from railway.features.slides.cache import _probe_fingerprint_sync

        head_resp = _make_http_response(b"", headers={"ETag": '"abc123"', "Last-Modified": "", "Content-Length": ""})

        with patch("urllib.request.urlopen", return_value=head_resp) as mock_open:
            result = _probe_fingerprint_sync("https://drive.google.com/export?id=X")

        assert result.startswith("hdr:")
        assert '"abc123"' in result
        # Only one request (HEAD)
        assert mock_open.call_count == 1
        req = mock_open.call_args[0][0]
        assert req.get_method() == "HEAD"

    def test_probe_fingerprint_uses_head_with_last_modified(self):
        """HEAD returns Last-Modified but no ETag → still hdr: format."""
        from railway.features.slides.cache import _probe_fingerprint_sync

        head_resp = _make_http_response(b"", headers={
            "ETag": "",
            "Last-Modified": "Wed, 01 Jan 2025 12:00:00 GMT",
            "Content-Length": "",
        })

        with patch("urllib.request.urlopen", return_value=head_resp):
            result = _probe_fingerprint_sync("https://example.com/file.pdf")

        assert result.startswith("hdr:")
        assert "Wed, 01 Jan 2025 12:00:00 GMT" in result

    def test_probe_fingerprint_fallback_get_on_405(self):
        """HEAD returns 405 → fall back to GET + SHA256 fingerprint."""
        from railway.features.slides.cache import _probe_fingerprint_sync

        pdf_data = b"%PDF-1.4 test content"
        expected_hash = hashlib.sha256(pdf_data).hexdigest()
        get_resp = _make_http_response(pdf_data)

        def _urlopen_side_effect(req, **kwargs):
            if req.get_method() == "HEAD":
                raise _make_http_error(405)
            return get_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen_side_effect) as mock_open:
            result = _probe_fingerprint_sync("https://example.com/file.pdf")

        assert result == f"body:{expected_hash}"
        assert mock_open.call_count == 2

    def test_probe_fingerprint_raises_on_non_405_error(self):
        """Non-405 HTTP errors should propagate."""
        from railway.features.slides.cache import _probe_fingerprint_sync

        with patch("urllib.request.urlopen", side_effect=_make_http_error(403)):
            with pytest.raises(urllib.error.HTTPError):
                _probe_fingerprint_sync("https://example.com/file.pdf")

    def test_probe_fingerprint_fallback_get_when_no_headers(self):
        """HEAD returns 200 but no ETag/LM/CL → fall back to GET + SHA256."""
        from railway.features.slides.cache import _probe_fingerprint_sync

        pdf_data = b"%PDF-1.4 no-headers content"
        expected_hash = hashlib.sha256(pdf_data).hexdigest()

        head_resp = _make_http_response(b"", headers={})
        get_resp = _make_http_response(pdf_data)

        call_count = [0]

        def _urlopen_side_effect(req, **kwargs):
            call_count[0] += 1
            if req.get_method() == "HEAD":
                return head_resp
            return get_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen_side_effect):
            result = _probe_fingerprint_sync("https://example.com/file.pdf")

        assert result == f"body:{expected_hash}"


# ---------------------------------------------------------------------------
# _download_pdf_sync tests
# ---------------------------------------------------------------------------

class TestDownloadPdfSync(unittest.TestCase):

    def test_download_pdf_saves_file(self, tmp_path=None):
        """Valid PDF data is written to the destination file."""
        import tempfile
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
        import tempfile
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
        import tempfile
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
# Concurrent request deduplication test
# ---------------------------------------------------------------------------

class TestConcurrentRequestDedup(unittest.TestCase):

    def test_concurrent_requests_dedup(self):
        """
        5 concurrent download_or_wait_cached calls → _download_pdf_sync called exactly once.
        The 4 waiters are unblocked by the asyncio.Event after the first download completes.
        """
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            async def _run():
                _reset_state()

                slug = "test-dedup-deck"
                url = "https://drive.google.com/export?id=DEDUP"

                state.slides_catalog[slug] = {
                    "slug": slug,
                    "title": "Test Dedup Deck",
                    "drive_export_url": url,
                }

                pdf_data = b"%PDF-1.4 dedup test content"
                download_call_count = [0]

                def _mock_download(url_, dest_):
                    download_call_count[0] += 1
                    dest_.parent.mkdir(parents=True, exist_ok=True)
                    dest_.write_bytes(pdf_data)
                    return len(pdf_data)

                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch.object(cache_mod, "_download_pdf_sync", side_effect=_mock_download),
                    patch.object(cache_mod, "_probe_fingerprint_sync", return_value="hdr:test|test|test"),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    tasks = [
                        asyncio.create_task(cache_mod.download_or_wait_cached(slug))
                        for _ in range(5)
                    ]
                    results = await asyncio.gather(*tasks)

                # All 5 should return a path
                assert all(r is not None for r in results)
                assert all(r.exists() for r in results)
                # The download function should have been called exactly once
                assert download_call_count[0] == 1

            run_async(_run())


# ---------------------------------------------------------------------------
# handle_slides_catalog test
# ---------------------------------------------------------------------------

class TestHandleSlidesCatalog(unittest.TestCase):

    def test_handle_slides_catalog(self):
        """Catalog entries are stored in state.slides_catalog and status is initialized."""
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            async def _run():
                _reset_state()
                entries = [
                    {"slug": "clean-code", "title": "Clean Code", "drive_export_url": "https://drive.google.com/export?id=CC"},
                    {"slug": "arch", "title": "Architecture", "drive_export_url": "https://drive.google.com/export?id=AR"},
                ]
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    await cache_mod.handle_slides_catalog(entries)

            run_async(_run())

        assert "clean-code" in state.slides_catalog
        assert "arch" in state.slides_catalog
        assert state.slides_catalog["clean-code"]["title"] == "Clean Code"
        assert state.slides_catalog["arch"]["drive_export_url"] == "https://drive.google.com/export?id=AR"

        # Status should be initialized for both slugs
        assert "clean-code" in state.slides_cache_status
        assert "arch" in state.slides_cache_status
        assert state.slides_cache_status["clean-code"]["status"] == "not_cached"
        assert state.slides_cache_status["arch"]["status"] == "not_cached"

    def test_handle_slides_catalog_detects_existing_cache(self):
        """Slugs with PDF already on disk get 'cached' status."""
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()
            # Pre-create a cached PDF
            (cache_dir / "clean-code.pdf").write_bytes(b"%PDF-1.4 already cached")

            async def _run():
                _reset_state()
                entries = [
                    {"slug": "clean-code", "title": "Clean Code", "drive_export_url": "https://drive.google.com/export?id=CC"},
                ]
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    await cache_mod.handle_slides_catalog(entries)

            run_async(_run())

        assert state.slides_cache_status["clean-code"]["status"] == "cached"

    def test_handle_slides_catalog_ignores_empty_slugs(self):
        """Entries with empty slug are silently ignored."""
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            async def _run():
                _reset_state()
                entries = [
                    {"slug": "", "title": "Empty Slug", "drive_export_url": "https://drive.google.com/export?id=X"},
                    {"slug": "valid-deck", "title": "Valid", "drive_export_url": "https://drive.google.com/export?id=Y"},
                ]
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch("railway.shared.messaging.broadcast", new_callable=AsyncMock),
                ):
                    await cache_mod.handle_slides_catalog(entries)

            run_async(_run())

        assert "" not in state.slides_catalog
        assert "valid-deck" in state.slides_catalog


# ---------------------------------------------------------------------------
# download_or_wait_cached tests
# ---------------------------------------------------------------------------

class TestDownloadOrWaitCached(unittest.TestCase):

    def test_returns_none_when_no_catalog_entry(self):
        """Returns None when slug is not in catalog."""
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()

            async def _run():
                _reset_state()
                with patch.object(cache_mod, "CACHE_DIR", cache_dir):
                    return await cache_mod.download_or_wait_cached("unknown-slug")

            result = run_async(_run())

        assert result is None

    def test_returns_existing_cached_path(self):
        """Returns cached file path immediately without downloading."""
        import tempfile
        from railway.features.slides import cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "slides-cache"
            cache_dir.mkdir()
            (cache_dir / "cached-deck.pdf").write_bytes(b"%PDF-1.4 already here")

            urlopen_mock = MagicMock()

            async def _run():
                _reset_state()
                state.slides_catalog["cached-deck"] = {
                    "slug": "cached-deck",
                    "title": "Cached Deck",
                    "drive_export_url": "https://example.com/file.pdf",
                }
                with (
                    patch.object(cache_mod, "CACHE_DIR", cache_dir),
                    patch("urllib.request.urlopen", urlopen_mock),
                ):
                    return await cache_mod.download_or_wait_cached("cached-deck")

            result = run_async(_run())

            # Assertions inside context while tmpdir still exists
            assert result is not None
            assert result.exists()
            urlopen_mock.assert_not_called()
