import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.state import state

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_ON_DEMAND_TIMEOUT_SECONDS = 60.0
_DEFAULT_ON_DEMAND_STALE_SECONDS = 60.0
_UPLOAD_STATE_TTL_SECONDS = 300.0
_upload_events: dict[str, asyncio.Event] = {}
_upload_locks: dict[str, asyncio.Lock] = {}
_daemon_send_lock = asyncio.Lock()


def _on_demand_enabled() -> bool:
    raw = os.environ.get("SLIDES_ON_DEMAND_UPLOAD_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _on_demand_timeout_seconds() -> float:
    raw = os.environ.get("SLIDES_ON_DEMAND_TIMEOUT_SECONDS", str(_DEFAULT_ON_DEMAND_TIMEOUT_SECONDS)).strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_ON_DEMAND_TIMEOUT_SECONDS


def _on_demand_stale_seconds() -> float:
    raw = os.environ.get("SLIDES_ON_DEMAND_STALE_SECONDS", str(_DEFAULT_ON_DEMAND_STALE_SECONDS)).strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_ON_DEMAND_STALE_SECONDS


def _upload_lock(slug: str) -> asyncio.Lock:
    lock = _upload_locks.get(slug)
    if lock is None:
        lock = asyncio.Lock()
        _upload_locks[slug] = lock
    return lock


def _upload_event(slug: str) -> asyncio.Event:
    event = _upload_events.get(slug)
    if event is None:
        event = asyncio.Event()
        _upload_events[slug] = event
    return event


def _cleanup_upload_states(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    keep: set[str] = set()
    for slug, entry in list(state.slides_uploads.items()):
        updated_at = entry.get("updated_at")
        age = (now - updated_at).total_seconds() if isinstance(updated_at, datetime) else _UPLOAD_STATE_TTL_SECONDS + 1
        if entry.get("status") == "uploading":
            keep.add(slug)
            continue
        if age <= _UPLOAD_STATE_TTL_SECONDS:
            keep.add(slug)
        else:
            state.slides_uploads.pop(slug, None)
            _upload_events.pop(slug, None)
            _upload_locks.pop(slug, None)
    for slug in keep:
        _upload_events.setdefault(slug, asyncio.Event())


async def _send_upload_request_to_daemon(slug: str, request_id: str, timeout_s: float) -> bool:
    ws = state.daemon_ws
    if ws is None:
        return False
    payload = {
        "type": "slides_upload_request",
        "slug": slug,
        "request_id": request_id,
        "timeout_s": int(timeout_s),
    }
    async with _daemon_send_lock:
        try:
            await ws.send_json(payload)
            logger.info("slides_upload_requested slug=%s request_id=%s", slug, request_id)
            return True
        except Exception as exc:
            logger.error("slides_upload_request_failed slug=%s request_id=%s err=%s", slug, request_id, exc)
            if state.daemon_ws is ws:
                state.daemon_ws = None
            return False


async def _wait_for_slide_upload(slug: str) -> Path:
    # Lazy import to avoid circular dependency at module load time.
    from features.slides.router import _resolve_slide_path

    timeout_s = _on_demand_timeout_seconds()
    stale_s = _on_demand_stale_seconds()
    now = datetime.now(timezone.utc)
    _cleanup_upload_states(now)

    path = _resolve_slide_path(slug)
    if path is not None:
        state.slides_uploads[slug] = {
            "status": "uploaded",
            "started_at": now,
            "updated_at": now,
            "request_id": None,
            "last_error": None,
        }
        return path

    should_send = False
    request_id = None
    lock = _upload_lock(slug)
    async with lock:
        now = datetime.now(timezone.utc)
        entry = state.slides_uploads.get(slug)
        if entry and entry.get("status") == "uploading" and isinstance(entry.get("started_at"), datetime):
            age = (now - entry["started_at"]).total_seconds()
            if age > stale_s:
                logger.warning("slides_upload_stale_retrigger slug=%s age=%.1fs", slug, age)
                should_send = True
            else:
                logger.info("slides_upload_wait slug=%s status=uploading age=%.1fs", slug, age)
        elif not entry or entry.get("status") != "uploaded":
            should_send = True

        if should_send:
            request_id = uuid.uuid4().hex
            event = asyncio.Event()
            _upload_events[slug] = event
            state.slides_uploads[slug] = {
                "status": "uploading",
                "started_at": now,
                "updated_at": now,
                "request_id": request_id,
                "last_error": None,
            }

    if should_send and request_id:
        sent = await _send_upload_request_to_daemon(slug, request_id, timeout_s)
        if not sent:
            async with lock:
                current = state.slides_uploads.get(slug)
                if current and current.get("request_id") == request_id:
                    current["status"] = "failed"
                    current["updated_at"] = datetime.now(timezone.utc)
                    current["last_error"] = "daemon unavailable"
                _upload_event(slug).set()
            raise HTTPException(status_code=503, detail="Slides service temporarily unavailable.")

    event = _upload_event(slug)
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        async with lock:
            current = state.slides_uploads.get(slug)
            if current and current.get("status") == "uploading":
                current["status"] = "failed"
                current["updated_at"] = datetime.now(timezone.utc)
                current["last_error"] = "timeout"
            event.set()
        logger.error("slides_upload_timeout slug=%s timeout=%.1fs", slug, timeout_s)
        raise HTTPException(status_code=504, detail="Slide upload timed out. Please retry.")

    path = _resolve_slide_path(slug)
    if path is None:
        entry = state.slides_uploads.get(slug, {})
        detail = "Slides service temporarily unavailable."
        if entry.get("last_error") == "timeout":
            detail = "Slide upload timed out. Please retry."
        raise HTTPException(status_code=503, detail=detail)
    return path


async def register_daemon_upload_result(payload: dict) -> None:
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        return
    status_value = str(payload.get("status") or "").strip().lower()
    request_id = str(payload.get("request_id") or "").strip() or None
    error = str(payload.get("error") or "").strip() or None
    now = datetime.now(timezone.utc)

    lock = _upload_lock(slug)
    async with lock:
        entry = state.slides_uploads.setdefault(slug, {})
        current_request_id = entry.get("request_id")
        if request_id and current_request_id and request_id != current_request_id:
            return

        if status_value == "uploaded":
            entry["status"] = "uploaded"
            entry["last_error"] = None
            logger.info("slides_upload_completed slug=%s request_id=%s", slug, request_id)
        else:
            entry["status"] = "failed"
            entry["last_error"] = error or "upload failed"
            logger.error("slides_upload_failed slug=%s request_id=%s err=%s", slug, request_id, entry["last_error"])
        entry["updated_at"] = now
        entry.setdefault("started_at", now)
        entry["request_id"] = request_id
        _upload_event(slug).set()


@router.get("/api/slides/participant-availability")
async def get_participant_slides_availability():
    from features.slides.router import _collect_participant_slides, _resolve_slide_path, _display_name_or_slug
    slides = _collect_participant_slides(include_unavailable_when_daemon_offline=True)
    entries: list[dict] = []
    for slide in slides:
        slug = str(slide.get("slug") or "").strip()
        raw_name = str(slide.get("name") or "").strip()
        display_name = _display_name_or_slug(raw_name, slug)
        path = _resolve_slide_path(slug) if slug else None
        entries.append({
            "name": display_name,
            "slug": slug,
            "source": slide.get("source"),
            "url": slide.get("url"),
            "available_on_server": bool(path is not None and path.exists()),
            "sync_status": slide.get("sync_status"),
            "sync_message": slide.get("sync_message"),
        })
    return {"entries": entries}


@router.get("/api/slides/upload-status/{slug}")
async def get_slide_upload_status(slug: str):
    now = datetime.now(timezone.utc)
    _cleanup_upload_states(now)
    entry = state.slides_uploads.get(slug)
    if not entry:
        return {"slug": slug, "status": "not_uploaded", "started_at": None, "age_seconds": None, "last_error": None}
    started_at = entry.get("started_at")
    age_seconds = None
    if isinstance(started_at, datetime):
        age_seconds = max(0.0, (now - started_at).total_seconds())
    return {
        "slug": slug,
        "status": entry.get("status", "not_uploaded"),
        "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
        "age_seconds": age_seconds,
        "last_error": entry.get("last_error"),
        "request_id": entry.get("request_id"),
        "updated_at": entry.get("updated_at").isoformat() if isinstance(entry.get("updated_at"), datetime) else None,
    }
