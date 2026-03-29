"""
Server-side PDF cache for Google Drive slides.

Downloads PDFs directly from Google Drive, caches them in /tmp/slides-cache/,
and serves them to participants. The daemon sends catalog info and invalidation signals.

Critical constraint: at most ONE in-flight HTTP request to Google Drive per slug at any time.
All GDrive HTTP calls go through a per-slug asyncio.Lock.
"""
import asyncio
import hashlib
import json
import logging
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from core.messaging import broadcast, broadcast_state
from core.state import state

logger = logging.getLogger(__name__)

CACHE_DIR = Path("/tmp/slides-cache")
_POLL_DELAY_S = 3.0       # wait before first fingerprint check
_POLL_INTERVAL_S = 3.0    # interval between fingerprint checks
_POLL_TIMEOUT_S = 60.0    # give up after this long
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
    catalog_entry = state.slides_catalog.get(slug)
    if catalog_entry:
        entry["title"] = catalog_entry.get("title", slug)
    # Carry updated_at from daemon slides list (PPTX mtime) if not already set
    if "updated_at" not in entry:
        slide = next((s for s in (state.slides or []) if s.get("slug") == slug), None)
        if slide and slide.get("updated_at"):
            entry["updated_at"] = slide["updated_at"]
    entry.update(extra)
    state.slides_cache_status[slug] = entry


def sync_slides_updated_at() -> None:
    """Propagate updated_at from state.slides into slides_cache_status (called after slides list changes)."""
    for slide in (state.slides or []):
        slug = slide.get("slug")
        updated_at = slide.get("updated_at")
        if slug and updated_at and slug in state.slides_cache_status:
            state.slides_cache_status[slug]["updated_at"] = updated_at


def _get_status(slug: str) -> str:
    """Return current status string or 'not_cached'."""
    entry = state.slides_cache_status.get(slug)
    if entry is None:
        return "not_cached"
    return entry.get("status", "not_cached")


def _cache_path(slug: str) -> Path:
    """Return the cache file path for a slug."""
    return CACHE_DIR / f"{slug}.pdf"


def _get_lock(slug: str) -> asyncio.Lock:
    """Lazy-create and return the per-slug GDrive lock."""
    if slug not in state.slides_gdrive_locks:
        state.slides_gdrive_locks[slug] = asyncio.Lock()
    return state.slides_gdrive_locks[slug]


def _get_event(slug: str) -> asyncio.Event:
    """Lazy-create and return the per-slug download event."""
    if slug not in state.slides_download_events:
        state.slides_download_events[slug] = asyncio.Event()
    return state.slides_download_events[slug]


# ---------------------------------------------------------------------------
# Sync functions (run in executor)
# ---------------------------------------------------------------------------

def _probe_fingerprint_sync(url: str) -> str:
    """
    Probe the remote URL for a fingerprint.
    HEAD first → ETag/Last-Modified/Content-Length → "hdr:{etag}|{lm}|{cl}".
    If HEAD 405 or no headers → GET + SHA256 → "body:{hash}".
    Raise on other errors.
    """
    ctx = _ssl_ctx()
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
            etag = resp.headers.get("ETag", "")
            lm = resp.headers.get("Last-Modified", "")
            cl = resp.headers.get("Content-Length", "")
            if etag or lm or cl:
                return f"hdr:{etag}|{lm}|{cl}"
            # HEAD succeeded but no useful headers — fall through to GET
    except urllib.error.HTTPError as e:
        if e.code != 405:
            raise

    # Fallback: GET + SHA256
    req_get = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req_get, context=ctx, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    return f"body:{digest}"


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


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

async def _probe_fingerprint(url: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _probe_fingerprint_sync, url)


async def _download_pdf(url: str, dest: Path) -> int:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_pdf_sync, url, dest)


# ---------------------------------------------------------------------------
# Core download (per-slug locked)
# ---------------------------------------------------------------------------

async def _do_download(slug: str, url: str) -> Path:
    """
    Acquire per-slug lock + global semaphore, download the PDF, update state.
    Returns cache path on success.
    """
    lock = _get_lock(slug)
    dest = _cache_path(slug)
    async with lock:
        async with state.slides_download_semaphore:
            _set_status(slug, "downloading")
            await broadcast_state()
            await _push_log(slug, "download_start", url)
            try:
                size = await _download_pdf(url, dest)
                # Probe and save fingerprint right after download
                try:
                    fp = await _probe_fingerprint(url)
                    state.slides_fingerprints[slug] = fp
                except Exception as fp_err:
                    logger.warning("[slides-cache] fingerprint probe failed for %s: %s", slug, fp_err)
                downloaded_at = datetime.now(timezone.utc).isoformat()
                _set_status(slug, "cached", size_bytes=size, downloaded_at=downloaded_at)
                await broadcast_state()
                size_mb = size / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{size / 1024:.0f} KB"
                await _push_log(slug, "download_complete", f"Downloaded PDF from Google Drive: {size_str}")
                return dest
            except Exception as exc:
                _set_status(slug, "download_failed", error=str(exc))
                await broadcast_state()
                await _push_log(slug, "download_failed", str(exc))
                raise
            except BaseException as exc:
                # Catches CancelledError (not a subclass of Exception in Python 3.8+)
                _set_status(slug, "download_failed", error=f"cancelled: {exc}")
                await broadcast_state()
                raise


# ---------------------------------------------------------------------------
# Public: serve or download on demand
# ---------------------------------------------------------------------------

async def download_or_wait_cached(slug: str) -> Path | None:
    """
    Return the cached PDF path for a slug, downloading if needed.

    - If the PDF is already on disk, return it immediately.
    - If no catalog entry, return None.
    - If a download is already in progress (lock held), await the event.
    - Otherwise: clear event, download, set event, return path.
    - On exception: set event anyway to unblock waiters; return stale if exists.
    """
    dest = _cache_path(slug)
    if dest.exists():
        return dest

    catalog_entry = state.slides_catalog.get(slug)
    if not catalog_entry:
        return None

    url = catalog_entry.get("drive_export_url")
    if not url:
        return None

    lock = _get_lock(slug)
    event = _get_event(slug)

    if lock.locked():
        # Someone else is downloading — wait for completion
        await event.wait()
        return dest if dest.exists() else None

    # We are the downloader
    event.clear()
    try:
        path = await _do_download(slug, url)
        return path
    except Exception:
        return dest if dest.exists() else None
    finally:
        event.set()


# ---------------------------------------------------------------------------
# Invalidation: fingerprint poll loop
# ---------------------------------------------------------------------------

async def handle_slide_invalidated(slug: str) -> None:
    """
    Called when the daemon signals that a slide may have changed.
    Starts a background fingerprint poll loop to detect the change.
    """
    current_status = _get_status(slug)
    if current_status in ("polling_drive", "downloading"):
        return

    catalog_entry = state.slides_catalog.get(slug)
    if not catalog_entry:
        return

    url = catalog_entry.get("drive_export_url")
    if not url:
        return

    dest = _cache_path(slug)
    new_status = "stale" if dest.exists() else "not_cached"
    _set_status(slug, new_status)
    await broadcast_state()
    await _push_log(slug, "invalidated", f"status={new_status}")

    asyncio.create_task(_poll_fingerprint_loop(slug, url))


async def _poll_fingerprint_loop(slug: str, url: str) -> None:
    """
    Poll GDrive fingerprint until it changes (then re-download) or timeout.
    All HTTP calls go through the per-slug lock.
    """
    import time
    lock = _get_lock(slug)

    # Get or establish baseline fingerprint
    old_fp = state.slides_fingerprints.get(slug)
    if old_fp is None:
        try:
            async with lock:
                old_fp = await _probe_fingerprint(url)
                state.slides_fingerprints[slug] = old_fp
        except Exception as exc:
            await _push_log(slug, "fingerprint_baseline_failed", str(exc))
            return

    _set_status(slug, "polling_drive")
    await broadcast_state()
    await _push_log(slug, "poll_start", f"baseline={old_fp[:30]}...")

    # Initial delay before first check
    await asyncio.sleep(_POLL_DELAY_S)

    deadline = time.monotonic() + _POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            async with lock:
                new_fp = await _probe_fingerprint(url)
        except Exception as exc:
            await _push_log(slug, "fingerprint_probe_error", str(exc))
            await asyncio.sleep(_POLL_INTERVAL_S)
            continue

        if new_fp != old_fp:
            await _push_log(slug, "fingerprint_changed", f"{old_fp[:20]}... -> {new_fp[:20]}...")
            state.slides_fingerprints[slug] = new_fp
            # Re-download
            event = _get_event(slug)
            event.clear()
            try:
                await _do_download(slug, url)
            except Exception:
                pass
            finally:
                event.set()
            return

        await asyncio.sleep(_POLL_INTERVAL_S)

    # Timed out
    elapsed = _POLL_DELAY_S + _POLL_TIMEOUT_S
    _set_status(slug, "poll_timeout")
    await broadcast_state()
    await _push_log(slug, "poll_timeout", f"after {elapsed:.0f}s")


# ---------------------------------------------------------------------------
# Catalog management
# ---------------------------------------------------------------------------

def seed_catalog_from_file() -> None:
    """
    Pre-populate state.slides_catalog from the static catalog JSON at startup.
    This lets the server download slides from Google Drive immediately, without
    waiting for the daemon to reconnect and send the catalog via WebSocket.
    Skips entries already present (so daemon-sent data always wins).
    """
    catalog_path = Path(__file__).resolve().parent.parent.parent / "daemon" / "materials_slides_catalog.json"
    if not catalog_path.exists():
        return
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return
    items = raw.get("decks") if isinstance(raw, dict) and "decks" in raw else []
    if not isinstance(items, list):
        return

    import re
    _slug_re = re.compile(r"[^a-z0-9]+")

    def _slugify(v: str) -> str:
        s = _slug_re.sub("-", v.strip().lower()).strip("-")
        return s or "slide"

    seeded = 0
    for entry in items:
        if not isinstance(entry, dict):
            continue
        target_pdf = str(entry.get("target_pdf") or "").strip()
        if not target_pdf:
            source = str(entry.get("source") or "").strip()
            if source:
                target_pdf = f"{Path(source).stem}.pdf"
        if not target_pdf:
            continue
        slug = _slugify(Path(target_pdf).stem)
        if slug in state.slides_catalog:
            continue
        drive_url = str(entry.get("drive_export_url") or "").strip()
        if not drive_url:
            continue
        state.slides_catalog[slug] = {
            "slug": slug,
            "title": str(entry.get("title") or slug),
            "drive_export_url": drive_url,
        }
        if slug not in state.slides_cache_status:
            dest = _cache_path(slug)
            initial_status = "cached" if dest.exists() else "not_cached"
            _set_status(slug, initial_status)
        seeded += 1
    if seeded:
        logger.info("slides: pre-seeded %d catalog entries from static file", seeded)


async def handle_slides_catalog(entries: list[dict]) -> None:
    """
    Populate state.slides_catalog from a list of {slug, title, drive_export_url} entries.
    For new slugs, check if already cached on disk and set initial status.
    """
    new_catalog: dict[str, dict] = {}
    for entry in entries:
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        cat_entry: dict = {
            "slug": slug,
            "title": str(entry.get("title") or slug),
            "drive_export_url": str(entry.get("drive_export_url") or ""),
        }
        if entry.get("updated_at"):
            cat_entry["updated_at"] = entry["updated_at"]
        new_catalog[slug] = cat_entry

    state.slides_catalog = new_catalog

    # Initialize status for each slug
    for slug in new_catalog:
        if slug not in state.slides_cache_status:
            dest = _cache_path(slug)
            initial_status = "cached" if dest.exists() else "not_cached"
            _set_status(slug, initial_status)

    await broadcast_state()
    await broadcast({"type": "slides_catalog_changed"})
    await _push_log("*", "catalog_loaded", f"{len(new_catalog)} entries")
