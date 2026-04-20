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
from railway.shared.state import state

router = APIRouter()
public_router = APIRouter()
daemon_router = APIRouter()  # global daemon-facing endpoints (no session prefix)
logger = logging.getLogger(__name__)

# Tracks the single active invalidation task per slug; new saves cancel the old one.
_pending_invalidate_tasks: dict[str, asyncio.Task] = {}


class SlideInvalidateRequest(BaseModel):
    drive_export_url: str = ""


@router.post("/api/slides/invalidate/{slug}")
async def invalidate_slide(slug: str, body: SlideInvalidateRequest | None = None):
    """Force Railway to re-download and cache-bust the PDF for slug.

    Called by the slides upload daemon after it detects a PPTX was saved and
    Google Drive has the updated PDF. Railway deletes the old cached file,
    re-downloads from Drive, then broadcasts slides_updated with
    refreshed_slugs so connected participants auto-reload the active slide.
    """
    from railway.features.slides.cache import _cache_path, _set_status, do_invalidate_download

    drive_export_url = (body.drive_export_url if body else "").strip()
    if not drive_export_url:
        for slide in (state.slides or []):
            if isinstance(slide, dict) and slide.get("slug") == slug:
                drive_export_url = str(slide.get("drive_export_url", "")).strip()
                break
    if not drive_export_url:
        raise HTTPException(status_code=422, detail=f"No drive_export_url found for slug={slug!r}")

    # Delete cached file and mark stale so any concurrent /check will re-download
    cached = _cache_path(slug)
    if cached.exists():
        cached.unlink(missing_ok=True)
    _set_status(slug, "stale")

    # Cancel any in-flight invalidation for this slug — keep only the most recent save.
    existing = _pending_invalidate_tasks.get(slug)
    if existing and not existing.done():
        logger.info("[slides] cancelling superseded invalidation task for slug=%s", slug)
        existing.cancel()

    task = asyncio.create_task(do_invalidate_download(slug, drive_export_url))
    _pending_invalidate_tasks[slug] = task
    task.add_done_callback(lambda t: _pending_invalidate_tasks.pop(slug, None))
    return {"status": "invalidating", "slug": slug}


class DownloadFromGdriveRequest(BaseModel):
    drive_export_url: str


class DownloadFromGdriveResponse(BaseModel):
    status: str
    sha256: str = ""
    size: int = 0


@daemon_router.post("/api/slides/download-from-gdrive/{slug}", response_model=DownloadFromGdriveResponse)
async def download_from_gdrive(slug: str, body: DownloadFromGdriveRequest):
    """Download PDF from Google Drive, cache it, return SHA256 hash.

    Called by the daemon to populate or refresh Railway's PDF cache.
    The daemon uses the returned hash to detect content changes.
    """
    from railway.features.slides.cache import _file_sha256, do_download

    drive_export_url = body.drive_export_url.strip()
    if not drive_export_url:
        raise HTTPException(status_code=422, detail="drive_export_url is required")

    try:
        path = await do_download(slug, drive_export_url)
        sha = _file_sha256(path)
        size = path.stat().st_size
        # Broadcast before returning — ensures participants see updated downloaded_at
        # before daemon's own _broadcast_slides_updated() fires (which omits downloaded_at).
        from railway.features.slides.cache import DecksUpdatedMsg
        from railway.shared.messaging import broadcast
        await broadcast(DecksUpdatedMsg(slides=state.slides or [], decks=state.slides_updated))
        return DownloadFromGdriveResponse(status="cached", sha256=sha, size=size)
    except Exception as exc:
        logger.exception("[slides] download-from-gdrive failed for slug=%s", slug)
        raise HTTPException(status_code=502, detail=str(exc)) from exc



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
