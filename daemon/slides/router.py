"""Daemon slides router — participant endpoints for slides list and PDF cache check."""
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.misc.state import misc_state

logger = logging.getLogger(__name__)

# Module-level state for pending /check futures
_pending_checks: dict[str, list[asyncio.Future]] = {}
_event_loop: asyncio.AbstractEventLoop | None = None


def get_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the daemon's FastAPI event loop (set on first /check request)."""
    return _event_loop


# ── Response models ──

class SlidesListResponse(BaseModel):
    slides: list[dict]
    cache_status: dict


# ── Participant router ──

participant_router = APIRouter(tags=["slides"])


@participant_router.get("/{session_id}/api/slides/check/{slug}")
async def check_slide_cache(session_id: str, slug: str):
    """Check if a PDF is cached; trigger download if not.

    Returns 200 immediately if already cached.
    Otherwise sends a download_pdf request to Railway and waits up to 30s.
    """
    global _event_loop

    # Already cached — return immediately
    if misc_state.slides_cache_status.get(slug, {}).get("status") == "cached":
        return JSONResponse({"status": "cached"}, status_code=200)

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
        result = await asyncio.wait_for(future, timeout=30.0)
    except asyncio.TimeoutError:
        # Remove timed-out future from pending list
        pending = _pending_checks.get(slug, [])
        if future in pending:
            pending.remove(future)
        if not pending:
            _pending_checks.pop(slug, None)
        return JSONResponse({"status": "timeout"}, status_code=503)

    if result == "ok":
        return JSONResponse({"status": "cached"}, status_code=200)
    return JSONResponse({"status": "error"}, status_code=503)


@participant_router.get("/{session_id}/api/slides")
async def list_slides(session_id: str):
    """Return the slides catalog with current cache status."""
    return SlidesListResponse(
        slides=list(misc_state.slides_catalog.values()),
        cache_status=misc_state.slides_cache_status,
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
        misc_state.slides_cache_status[slug] = {
            **misc_state.slides_cache_status.get(slug, {}),
            "status": "error",
        }

    # Broadcast updated cache status to all participants
    from daemon.ws_publish import broadcast
    from daemon.ws_messages import SlidesCacheStatusMsg
    broadcast(SlidesCacheStatusMsg(slides_cache_status=misc_state.slides_cache_status))

    # Resolve pending /check futures for this slug (thread-safe)
    futures = _pending_checks.pop(slug, [])
    if _event_loop is not None:
        for fut in futures:
            if not fut.done():
                _event_loop.call_soon_threadsafe(fut.set_result, status)
