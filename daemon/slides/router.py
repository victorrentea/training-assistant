"""Daemon slides router — participant endpoints for slides list and PDF cache check."""
import asyncio
import logging
import os
import socket
import urllib.error
import urllib.request

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.misc.state import misc_state
from daemon.slides.daemon import _ssl_context

logger = logging.getLogger(__name__)

# Module-level state for pending /check futures
_pending_checks: dict[str, list[asyncio.Future]] = {}
_event_loop: asyncio.AbstractEventLoop | None = None
_CHECK_TIMEOUT_S: float = 30.0
_RAILWAY_CHECK_TIMEOUT_S: float = 3.0


def get_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the daemon's FastAPI event loop (set on first /check request)."""
    return _event_loop


def _railway_download_url(session_id: str, slug: str) -> str:
    base = os.environ.get("WORKSHOP_SERVER_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/{session_id}/api/slides/download/{slug}"


def _is_cached_on_railway(session_id: str, slug: str) -> bool:
    url = _railway_download_url(session_id, slug)
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=_RAILWAY_CHECK_TIMEOUT_S, context=_ssl_context()) as resp:
            return 200 <= int(resp.status) < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        logger.warning("slides/check: railway HEAD failed for slug=%s code=%s", slug, exc.code)
        return False
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        logger.warning("slides/check: railway HEAD failed for slug=%s error=%s", slug, exc)
        return False


def _mark_cache_status(slug: str, status: str, **extra) -> None:
    misc_state.slides_cache_status[slug] = {
        **misc_state.slides_cache_status.get(slug, {}),
        "status": status,
        **extra,
    }


# ── Response models ──

class SlidesListResponse(BaseModel):
    slides: list[dict]


def _slides_with_embedded_cache_status() -> list[dict]:
    slides: list[dict] = []
    for raw in list(misc_state.slides_catalog.values()):
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        slug = str(entry.get("slug", "")).strip()
        status_entry = misc_state.slides_cache_status.get(slug, {}) if slug else {}
        if isinstance(status_entry, dict):
            entry.update(status_entry)
        if "status" not in entry:
            entry["status"] = "not_cached"
        slides.append(entry)
    return slides


# ── Participant router ──

participant_router = APIRouter(tags=["slides"])


@participant_router.get("/{session_id}/api/slides/check/{slug}")
async def check_slide_cache(session_id: str, slug: str):
    """Check if a PDF is cached; trigger download if not.

    Returns 200 immediately if already cached.
    Otherwise sends a download_pdf request to Railway and waits up to 30s.
    """
    global _event_loop

    # Fast path: cached in daemon state AND currently downloadable on Railway.
    if (
        misc_state.slides_cache_status.get(slug, {}).get("status") == "cached"
        and _is_cached_on_railway(session_id, slug)
    ):
        return JSONResponse({"status": "cached"}, status_code=200)
    if misc_state.slides_cache_status.get(slug, {}).get("status") == "cached":
        _mark_cache_status(slug, "not_cached", reason="railway_miss_after_cached")

    # Capture event loop for thread-safe future resolution from ws handler
    _event_loop = asyncio.get_event_loop()
    future: asyncio.Future = _event_loop.create_future()

    already_pending = slug in _pending_checks
    _pending_checks.setdefault(slug, []).append(future)

    # Only send download_pdf once per slug (coalesce concurrent requests)
    if not already_pending:
        drive_export_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url")
        from daemon.ws_publish import send_to_railway
        sent = send_to_railway({
            "type": "download_pdf",
            "slug": slug,
            "drive_export_url": drive_export_url,
        })
        if not sent:
            logger.warning("slides/check: ws_client not available, cannot request download for slug=%s", slug)

    try:
        result = await asyncio.wait_for(future, timeout=_CHECK_TIMEOUT_S)
    except asyncio.TimeoutError:
        # Remove timed-out future from pending list
        pending = _pending_checks.get(slug, [])
        if future in pending:
            pending.remove(future)
        if not pending:
            _pending_checks.pop(slug, None)
        _mark_cache_status(slug, "poll_timeout", reason="timeout_waiting_pdf_download_complete")
        return JSONResponse({"status": "timeout"}, status_code=503)

    if result == "ok":
        return JSONResponse({"status": "cached"}, status_code=200)
    _mark_cache_status(slug, "download_failed", reason="railway_reported_error")
    return JSONResponse({"status": "error"}, status_code=503)


@participant_router.get("/{session_id}/api/slides")
async def list_slides(session_id: str):
    """Return slides catalog with cache status embedded per slide."""
    return SlidesListResponse(
        slides=_slides_with_embedded_cache_status(),
    )


# ── WS handler: called from main thread via drain_queue() ──

def handle_pdf_download_complete(data: dict):
    """Handle pdf_download_complete message from Railway."""
    slug = data.get("slug", "").strip()
    status = data.get("status", "error")

    # Update cache status
    if status == "ok":
        misc_state.slides_cache_status[slug] = {
            **misc_state.slides_cache_status.get(slug, {}),
            "status": "cached",
        }
    else:
        _mark_cache_status(slug, "download_failed", reason="railway_reported_error")

    # Broadcast updated cache status to all participants
    from daemon.ws_publish import broadcast
    from daemon.ws_messages import SlidesCacheStatusMsg
    broadcast(
        SlidesCacheStatusMsg(
            slides=_slides_with_embedded_cache_status(),
            slides_cache_status=misc_state.slides_cache_status,
        )
    )

    # Resolve pending /check futures for this slug (thread-safe)
    futures = _pending_checks.pop(slug, [])
    if _event_loop is not None:
        for fut in futures:
            if not fut.done():
                _event_loop.call_soon_threadsafe(fut.set_result, status)
