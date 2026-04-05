import logging
import os
import json
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from railway.features.slides.upload import (
    _slugify,
    _uploaded_slides_dir,
)
from railway.features.ws.proxy_bridge import proxy_to_daemon

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)


def _merge_embedded_slide_status(payload: dict) -> dict:
    raw_slides = payload.get("slides")
    slides = raw_slides if isinstance(raw_slides, list) else []
    cache_status = payload.get("cache_status")
    cache_map = cache_status if isinstance(cache_status, dict) else {}

    merged_slides: list[dict] = []
    for raw in slides:
        if not isinstance(raw, dict):
            continue
        slide = dict(raw)
        slug = str(slide.get("slug", "")).strip()
        status_entry = cache_map.get(slug) if slug else None
        if isinstance(status_entry, dict):
            slide.update(status_entry)
        if "status" not in slide:
            slide["status"] = "not_cached"
        merged_slides.append(slide)

    merged = dict(payload)
    merged["slides"] = merged_slides
    merged.pop("cache_status", None)
    return merged


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
    response = await proxy_to_daemon(
        method="GET",
        path=path,
        body=None,
        headers=dict(request.headers),
        participant_id=None,
    )
    if response.status_code != 200:
        return {"slides": []}
    try:
        raw_body = response.body or b"{}"
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            return {"slides": []}
        return _merge_embedded_slide_status(payload)
    except Exception:
        logger.exception("Failed to normalize /api/slides payload from daemon")
        return {"slides": []}


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
