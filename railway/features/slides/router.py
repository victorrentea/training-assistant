import asyncio
import logging
import os
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
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


class _SlideFileResponse(FileResponse):
    # Starlette reads a file in 64 KB chunks, each a thread hop plus an ASGI send.
    # A talk's phones pull the deck in 1 MB ranges, so bigger reads cut the
    # per-phone CPU of this single-worker relay by about a third (measured).
    chunk_size = 256 * 1024


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



class DeckStoredResponse(BaseModel):
    status: str
    sha256: str
    size: int
    pages: int = 0


async def _deck_stored(slug: str, data: bytes, what: str) -> DeckStoredResponse:
    """Put the deck in the cache and tell the daemon, exactly as after a download from
    Google Drive: its "download_slide_completed" is what makes participants reload."""
    import hashlib
    from datetime import datetime

    from railway.features.slides.cache import _cache_path, _push_log, _set_status
    from railway.features.slides.pages import write_atomically

    await asyncio.to_thread(write_atomically, _cache_path(slug), data)
    downloaded_at = datetime.now(timezone.utc).isoformat()
    _set_status(slug, "cached", size_bytes=len(data), downloaded_at=downloaded_at)
    await _push_log(slug, "download_slide_completed", f"{what}: {len(data) / (1024 * 1024):.1f} MB",
                    downloaded_at=downloaded_at)
    return DeckStoredResponse(status="cached", sha256=hashlib.sha256(data).hexdigest(), size=len(data))


async def _read_pdf(file: UploadFile) -> bytes:
    from railway.features.slides.pages import MAX_DECK_BYTES

    data = await file.read(MAX_DECK_BYTES + 1)
    if len(data) > MAX_DECK_BYTES:
        raise HTTPException(status_code=413, detail="PDF too large")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Not a PDF")
    return data


@daemon_router.post("/api/slides/deck/{slug}", response_model=DeckStoredResponse)
async def store_deck(slug: str, file: UploadFile = File(...)):
    """The whole deck as PowerPoint prints it (daemon/slides/local_publish.py): replaces
    whatever is cached for the slug, Google Drive's conversion included."""
    return await _deck_stored(_slugify(slug), await _read_pdf(file), "Deck printed by PowerPoint")


@daemon_router.post("/api/slides/pages/{slug}", response_model=DeckStoredResponse)
async def replace_deck_pages(
    slug: str,
    base_sha256: str = Form(...),
    positions: str = Form(...),
    file: UploadFile = File(...),
):
    """Only the pages a save changed, put into the cached deck at `positions` (a JSON list,
    1-based). 409 unless the cached deck is the one the daemon thinks it is (`base_sha256`):
    after a restart, or with Google Drive's version in the cache, it must send the whole deck."""
    import json

    from railway.features.slides.cache import _cache_path, _file_sha256
    from railway.features.slides.pages import PagesDoNotFit, replace_pages

    slug = _slugify(slug)
    cached = _cache_path(slug)
    if not cached.exists() or await asyncio.to_thread(_file_sha256, cached) != base_sha256:
        raise HTTPException(status_code=409, detail="The cached deck is not the one these pages belong to")
    try:
        wanted = json.loads(positions)
        if not isinstance(wanted, list) or not all(isinstance(p, int) and not isinstance(p, bool) for p in wanted):
            raise ValueError("positions must be a list of integers")
        pages = await _read_pdf(file)
        merged = await asyncio.to_thread(replace_pages, cached.read_bytes(), pages, wanted)
    except (ValueError, PagesDoNotFit) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stored = await _deck_stored(slug, merged, f"Slides {wanted} printed by PowerPoint")
    stored.pages = len(wanted)
    return stored


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
        return _SlideFileResponse(path=path, media_type="application/pdf", filename=path.name, headers=headers)
    return _SlideFileResponse(path=path, media_type="application/pdf", headers=headers)
