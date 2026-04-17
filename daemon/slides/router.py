"""Daemon slides router — participant endpoints for slides list and PDF cache check."""
import asyncio
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.misc.state import misc_state
from daemon.slides.daemon import _ssl_context

logger = logging.getLogger(__name__)

_RAILWAY_CHECK_TIMEOUT_S: float = 3.0
_RAILWAY_DOWNLOAD_TIMEOUT_S: float = 120.0  # Railway downloads can take 10-15s from Drive

# Module-level event loop reference — used by __main__.py for async scheduling
# from the main (sync) thread (e.g. backfill location metadata, overlay notifications).
_event_loop: asyncio.AbstractEventLoop | None = None


def get_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the daemon's FastAPI event loop."""
    return _event_loop


def _railway_base_url() -> str:
    return os.environ.get("WORKSHOP_SERVER_URL", "http://localhost:8000").rstrip("/")


def _railway_download_url(session_id: str, slug: str) -> str:
    return f"{_railway_base_url()}/{session_id}/api/slides/download/{slug}"


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


def _railway_auth_header() -> str:
    """Build Basic Auth header for daemon→Railway HTTP calls."""
    import base64
    user = os.environ.get("HOST_USERNAME", "host")
    password = os.environ.get("HOST_PASSWORD", "")
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def download_on_railway(slug: str, drive_export_url: str) -> dict:
    """Call Railway REST to download PDF from Google Drive and cache it.

    Returns dict with {status, sha256, size} on success.
    Raises on failure (HTTP error, timeout, etc.).
    """
    url = f"{_railway_base_url()}/api/slides/download-from-gdrive/{slug}"
    body = json.dumps({"drive_export_url": drive_export_url}).encode()
    req = urllib.request.Request(
        url, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": _railway_auth_header(),
        },
        data=body,
    )
    with urllib.request.urlopen(req, timeout=_RAILWAY_DOWNLOAD_TIMEOUT_S, context=_ssl_context()) as resp:
        return json.loads(resp.read())


def _mark_cache_status(slug: str, status: str, **extra) -> None:
    misc_state.slides_updated[slug] = {
        **misc_state.slides_updated.get(slug, {}),
        "status": status,
        **extra,
    }


# ── Response models ──

class SlidesListResponse(BaseModel):
    slides: list[dict]


class SlidesCheckResponse(BaseModel):
    status: str


def _slides_with_embedded_cache_status() -> list[dict]:
    slides: list[dict] = []
    seen_slugs: set[str] = set()
    for raw in list(misc_state.slides_catalog.values()):
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        slug = str(entry.get("slug", "")).strip()
        status_entry = misc_state.slides_updated.get(slug, {}) if slug else {}
        if isinstance(status_entry, dict):
            entry.update(status_entry)
        if "status" not in entry:
            entry["status"] = "not_cached"
        slides.append(entry)
        if slug:
            seen_slugs.add(slug)

    # Include runtime-uploaded slides (.server-data/uploaded-slides/*.pdf)
    # so participant catalog updates immediately after /api/slides/upload.
    uploaded_dir = _uploaded_slides_dir()
    if uploaded_dir.exists() and uploaded_dir.is_dir():
        for pdf in sorted(uploaded_dir.glob("*.pdf")):
            slug = pdf.stem.strip()
            if not slug or slug in seen_slugs:
                continue
            meta_name, meta_updated_at = _uploaded_slide_meta(slug)
            slides.append(
                {
                    "slug": slug,
                    "name": meta_name or slug,
                    "title": meta_name or slug,
                    "url": f"/api/slides/download/{slug}",
                    "updated_at": meta_updated_at,
                    "status": "cached",
                }
            )
            seen_slugs.add(slug)
    return slides


def _uploaded_slides_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".server-data") / "uploaded-slides"


def _uploaded_slide_meta(slug: str) -> tuple[str, str | None]:
    meta_path = _uploaded_slides_dir() / f"{slug}.json"
    if not meta_path.exists():
        return "", None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return "", None
    if not isinstance(payload, dict):
        return "", None
    name = str(payload.get("name") or "").strip()
    updated_at = payload.get("updated_at")
    return name, str(updated_at) if updated_at else None


def _broadcast_slides_updated(refreshed_slugs: list[str] | None = None) -> None:
    from daemon.ws_messages import SlidesCacheStatusMsg
    from daemon.ws_publish import broadcast
    broadcast(SlidesCacheStatusMsg(refreshed_slugs=refreshed_slugs or []))


# ── Participant router ──

participant_router = APIRouter(tags=["slides"])


@participant_router.get("/{session_id}/api/slides/check/{slug}", response_model=SlidesCheckResponse)
async def check_slide_cache(session_id: str, slug: str, force: bool = False):
    """Check if a PDF is cached; trigger download if not.

    Returns 200 immediately if already cached.
    Otherwise calls Railway REST to download from Google Drive (blocking).
    Pass ?force=true to bypass the fast-path cache check and verify with Railway.
    """
    global _event_loop
    _event_loop = asyncio.get_event_loop()

    # Fast path: trust daemon-side cache status (kept in sync via WS reconnect probing).
    if not force and misc_state.slides_updated.get(slug, {}).get("status") == "cached":
        return SlidesCheckResponse(status="cached")

    drive_export_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url")
    if not drive_export_url:
        return JSONResponse({"status": "error", "detail": "no drive_export_url"}, status_code=404)

    _mark_cache_status(slug, "downloading")
    _broadcast_slides_updated()

    try:
        result = await asyncio.to_thread(download_on_railway, slug, drive_export_url)
        _mark_cache_status(slug, "cached", last_sha256=result.get("sha256", ""))
        _broadcast_slides_updated()
        return SlidesCheckResponse(status="cached")
    except Exception as exc:
        logger.warning("slides/check: Railway download failed for slug=%s: %s", slug, exc)
        _mark_cache_status(slug, "download_failed", reason=str(exc))
        # Do NOT broadcast on failure — the 503 response tells the requesting
        # participant. Broadcasting would trigger follow-retry storms in all
        # connected participants.
        return JSONResponse({"status": "error"}, status_code=503)


@participant_router.get("/{session_id}/api/slides")
async def list_slides(session_id: str):
    """Return slides catalog with cache status embedded per slide."""
    return SlidesListResponse(slides=_slides_with_embedded_cache_status())


