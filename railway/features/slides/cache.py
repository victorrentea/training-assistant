"""
Server-side PDF cache for Google Drive slides.

Downloads PDFs directly from Google Drive and caches them in /tmp/slides-cache/.
The daemon instructs Railway to fetch a PDF via the download_pdf WS message,
providing the drive_export_url inline. Railway does not maintain a slides catalog.
"""
import asyncio
import json
import logging
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from railway.shared.messaging import broadcast
from railway.shared.state import state

logger = logging.getLogger(__name__)

CACHE_DIR = Path("/tmp/slides-cache")
_DOWNLOAD_TIMEOUT_S = 60  # single HTTP download timeout


# ---------------------------------------------------------------------------
# SSL context
# ---------------------------------------------------------------------------

def _ssl_ctx() -> ssl.SSLContext:
    """Create SSL context, trying certifi first with fallback to default."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except Exception:
        return ssl.create_default_context()


# ---------------------------------------------------------------------------
# Logging / status helpers
# ---------------------------------------------------------------------------

async def _push_log(slug: str, event: str, detail: str = "") -> None:
    """Send a slide_log message to the daemon WS and log locally."""
    msg = {"type": "slide_log", "slug": slug, "event": event, "detail": detail}
    logger.info("[slides-cache] %s slug=%s %s", event, slug, detail)
    ws = state.daemon_ws
    if ws is not None:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            pass


def _set_status(slug: str, status: str, **extra) -> None:
    """Update slides_cache_status for a slug."""
    entry = state.slides_cache_status.get(slug) or {}
    entry = {**entry, "status": status}
    entry.update(extra)
    state.slides_cache_status[slug] = entry


def _cache_path(slug: str) -> Path:
    """Return the cache file path for a slug."""
    return CACHE_DIR / f"{slug}.pdf"


async def broadcast_slides_cache_status() -> None:
    """Broadcast slides_cache_status as a dedicated message (separate from full state)."""
    await broadcast({"type": "slides_cache_status", "slides_cache_status": state.slides_cache_status})


# ---------------------------------------------------------------------------
# Sync download (run in executor)
# ---------------------------------------------------------------------------

def _download_pdf_sync(url: str, dest: Path) -> int:
    """
    Download from url, verify it starts with %PDF, write to dest.
    Returns size in bytes.
    Raises RuntimeError if content is not a PDF.
    """
    ctx = _ssl_ctx()
    req = urllib.request.Request(url, method="GET")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, context=ctx, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(
            f"Downloaded content for slug does not start with %PDF (got {data[:20]!r})"
        )
    dest.write_bytes(data)
    return len(data)


async def _download_pdf(url: str, dest: Path) -> int:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_pdf_sync, url, dest)


# ---------------------------------------------------------------------------
# Core download — called by Railway WS handler on daemon instruction
# ---------------------------------------------------------------------------

async def do_download(slug: str, url: str) -> Path:
    """
    Download the PDF for slug from url, update cache status, and return the cache path.
    Raises on failure.
    """
    dest = _cache_path(slug)
    _set_status(slug, "downloading")
    await broadcast_slides_cache_status()
    await _push_log(slug, "download_start", url)
    try:
        size = await _download_pdf(url, dest)
        downloaded_at = datetime.now(timezone.utc).isoformat()
        _set_status(slug, "cached", size_bytes=size, downloaded_at=downloaded_at)
        await broadcast_slides_cache_status()
        size_mb = size / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size / 1024:.0f} KB"
        await _push_log(slug, "download_complete", f"Downloaded PDF from Google Drive: {size_str}")
        return dest
    except Exception as exc:
        _set_status(slug, "download_failed", error=str(exc))
        await broadcast_slides_cache_status()
        await _push_log(slug, "download_failed", str(exc))
        raise
