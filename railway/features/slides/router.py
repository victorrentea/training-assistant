import logging
import os
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from railway.features.slides.upload import (
    _slugify,
    _uploaded_slides_dir,
)

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)


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
    from railway.features.ws.proxy_bridge import proxy_to_daemon
    sid = request.path_params.get("session_id", "")
    path = f"/{sid}/api/slides" if sid else "/api/slides"
    response = await proxy_to_daemon(
        method="GET",
        path=path,
        body=None,
        headers=dict(request.headers),
        participant_id=None,
    )
    if response.status_code != 200:
        return {"slides": [], "cache_status": {}}
    return response


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
