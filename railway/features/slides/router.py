import asyncio
import logging
import os
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from railway.features.slides.upload import (
    _slugify,
    _uploaded_slides_dir,
)
from railway.features.ws.proxy_bridge import proxy_to_daemon

router = APIRouter()
public_router = APIRouter()
daemon_router = APIRouter()  # global daemon-facing endpoints (no session prefix)
logger = logging.getLogger(__name__)

# Per-slug deduplication: parallel refresh requests for the same slug share
# one in-flight fetch instead of racing each other to the cache file.
_pending_refresh: dict[str, asyncio.Future] = {}


class RefreshSlideRequest(BaseModel):
    drive_export_url: str


class RefreshSlideResponse(BaseModel):
    status: str
    sha256: str = ""
    size: int = 0


@daemon_router.post("/api/slides/refresh/{slug}", response_model=RefreshSlideResponse)
async def refresh_slide(slug: str, body: RefreshSlideRequest):
    """Ensure cache_dir/{slug}.pdf is the latest version from Google Drive.

    Unifies the previous /api/slides/download-from-gdrive (called on
    participant cache miss) and /api/slides/invalidate (called when the
    daemon's PPTX watcher detects a file change). Both did the same
    underlying work — fetch from Drive, write to cache, notify daemon —
    just with different sync/async transport choices.

    Behavior:
    - Marks status=stale up front so concurrent /check callers wait
      instead of serving the old PDF.
    - Per-slug deduplication: parallel calls for the same slug share one
      in-flight fetch (e.g. participant cache miss + PPTX-watcher
      invalidate firing simultaneously).
    - Deletes the cache file (no-op when absent — covers cache-miss too).
    - Calls do_download which sends slide_log "completed" to the daemon;
      the daemon broadcasts decks_updated to participants.
    - Returns SHA256 + size so the caller can detect content changes.

    Synchronous: the caller awaits the response when it needs the SHA
    (cache-miss path) or fire-and-forgets when it doesn't (PPTX update).
    """
    from railway.features.slides.cache import _cache_path, _file_sha256, _set_status, do_download

    drive_export_url = (body.drive_export_url or "").strip()
    if not drive_export_url:
        raise HTTPException(status_code=422, detail="drive_export_url is required")

    existing = _pending_refresh.get(slug)
    if existing is not None and not existing.done():
        try:
            return await asyncio.shield(existing)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_refresh[slug] = fut
    try:
        _set_status(slug, "stale")
        cached = _cache_path(slug)
        if cached.exists():
            cached.unlink(missing_ok=True)
        path = await do_download(slug, drive_export_url)
        sha = _file_sha256(path)
        size = path.stat().st_size
        result = RefreshSlideResponse(status="cached", sha256=sha, size=size)
        fut.set_result(result)
        return result
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        logger.exception("[slides] refresh failed for slug=%s", slug)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _pending_refresh.pop(slug, None)



def _resolve_local_slides_dir() -> Path | None:
    candidates: list[Path] = []
    env_dir = os.environ.get("TRAINING_ASSISTANT_SLIDES_DIR")
    publish_dir = os.environ.get("PPTX_PUBLISH_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    if publish_dir:
        candidates.append(Path(publish_dir).expanduser())
    candidates.append(Path("/app/server_materials/slides"))
    candidates.append(Path("server_materials") / "slides")
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _resolve_slide_path(slug: str) -> Path | None:
    # Check local slides dir
    slides_dir = _resolve_local_slides_dir()
    if slides_dir:
        for pdf in slides_dir.iterdir():
            if pdf.is_file() and pdf.suffix.lower() == ".pdf" and _slugify(pdf.stem) == slug:
                return pdf
    # Check uploaded slides dir
    uploaded_dir = _uploaded_slides_dir()
    if uploaded_dir.exists() and uploaded_dir.is_dir():
        for pdf in uploaded_dir.iterdir():
            if pdf.is_file() and pdf.suffix.lower() == ".pdf" and _slugify(pdf.stem) == slug:
                return pdf
    return None


def _slide_etag(path: Path) -> str:
    stat = path.stat()
    return f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def _slide_last_modified(path: Path) -> str:
    return formatdate(path.stat().st_mtime, usegmt=True)


def _is_not_modified(request: Request, etag: str, path: Path) -> bool:
    inm = request.headers.get("if-none-match", "")
    if inm:
        tokens = [token.strip() for token in inm.split(",") if token.strip()]
        if "*" in tokens or etag in tokens:
            return True

    ims = request.headers.get("if-modified-since", "").strip()
    if ims:
        try:
            since_dt = parsedate_to_datetime(ims)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            since_ts = int(since_dt.timestamp())
            mtime_ts = int(path.stat().st_mtime)
            if since_ts >= mtime_ts:
                return True
        except Exception:
            pass
    return False


@public_router.get("/api/slides")
async def get_slides(request: Request):
    sid = request.path_params.get("session_id", "")
    path = f"/{sid}/api/slides" if sid else "/api/slides"
    return await proxy_to_daemon(
        method="GET",
        path=path,
        body=None,
        headers=dict(request.headers),
        participant_id=None,
    )


@public_router.get("/api/slides/check/{slug}")
async def check_slide(slug: str, request: Request):
    sid = request.path_params.get("session_id", "")
    path = f"/{sid}/api/slides/check/{slug}" if sid else f"/api/slides/check/{slug}"
    return await proxy_to_daemon(
        method="GET",
        path=path,
        body=None,
        headers=dict(request.headers),
        participant_id=request.headers.get("x-participant-id"),
        timeout=35.0,
    )


@public_router.api_route("/api/slides/download/{slug}", methods=["GET", "HEAD"], include_in_schema=False)
@public_router.get("/api/slides/download/{slug}", operation_id="get_slide_download")
async def get_slide_file(slug: str, request: Request):
    from railway.features.slides.cache import _cache_path

    # 1. Check local / uploaded
    path = _resolve_slide_path(slug)

    # 2. Check cache dir (populated by daemon-instructed downloads)
    if not path:
        cached = _cache_path(slug)
        if cached.exists():
            path = cached

    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    etag = _slide_etag(path)
    headers = {
        "ETag": etag,
        "Last-Modified": _slide_last_modified(path),
        "Cache-Control": "no-cache",
    }
    if _is_not_modified(request, etag, path):
        return Response(status_code=304, headers=headers)
    force_download = request.query_params.get("download") == "1"
    disposition = "attachment" if force_download else "inline"
    headers = {**headers, "Content-Disposition": f'{disposition}; filename="{path.name}"'}
    if force_download:
        return FileResponse(path=path, media_type="application/pdf", filename=path.name, headers=headers)
    return FileResponse(path=path, media_type="application/pdf", headers=headers)
