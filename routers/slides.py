import asyncio
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, field_validator

from messaging import broadcast_state
from state import state

router = APIRouter()
public_router = APIRouter()
_SLUG_RE = re.compile(r"[^a-z0-9]+")
logger = logging.getLogger(__name__)

_DEFAULT_ON_DEMAND_TIMEOUT_SECONDS = 60.0
_DEFAULT_ON_DEMAND_STALE_SECONDS = 60.0
_UPLOAD_STATE_TTL_SECONDS = 300.0
_upload_events: dict[str, asyncio.Event] = {}
_upload_locks: dict[str, asyncio.Lock] = {}
_daemon_send_lock = asyncio.Lock()


class SlidesUpdate(BaseModel):
    url: str
    slug: str
    source_file: str | None = None
    converter: str | None = None
    updated_at: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("slug cannot be empty")
        if "/" in cleaned or "\\" in cleaned:
            raise ValueError("slug cannot contain path separators")
        return cleaned


class MaterialsDeleteRequest(BaseModel):
    relative_path: str


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _is_displayable_slide_name(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    return any(ch.isalnum() for ch in cleaned)


def _candidate_local_slides_dirs() -> list[Path]:
    env_dir = os.environ.get("TRAINING_ASSISTANT_SLIDES_DIR")
    publish_dir = os.environ.get("PPTX_PUBLISH_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    if publish_dir:
        candidates.append(Path(publish_dir).expanduser())
    # Railway runtime path where daemon-published slides are mirrored.
    candidates.append(Path("/app/server_materials/slides"))
    # Local fallback for non-Railway runs from repo root.
    candidates.append(Path("server_materials") / "slides")
    return candidates


def _resolve_local_slides_dir() -> Path | None:
    for candidate in _candidate_local_slides_dirs():
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _resolve_catalog_file() -> Path:
    configured = os.environ.get("PPTX_CATALOG_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "daemon" / "materials_slides_catalog.json"


def _normalize_catalog_map_entry(raw: dict) -> dict | None:
    source_value = str(raw.get("source") or "").strip()
    if not source_value:
        return None
    source = Path(source_value).expanduser()
    target_pdf = str(raw.get("target_pdf") or "").strip()
    if not target_pdf:
        target_pdf = f"{source.stem}.pdf"
    if not target_pdf.lower().endswith(".pdf"):
        target_pdf += ".pdf"
    target_pdf = target_pdf.replace("/", "-").replace("\\", "-")

    exists = source.exists() and source.is_file()
    updated_at = None
    if exists:
        updated_at = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat()

    return {
        "pdf": target_pdf,
        "pptx_path": str(source),
        "exists": exists,
        "updated_at": updated_at,
    }


def _load_catalog_map_entries(path: Path) -> list[dict]:
    if not path.exists() or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("slides") if isinstance(raw, dict) and "slides" in raw else raw
    if not isinstance(items, list):
        return []
    entries: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_catalog_map_entry(item)
        if normalized:
            entries.append(normalized)
    entries.sort(key=lambda entry: (entry["pdf"].lower(), entry["pptx_path"].lower()))
    return entries


def _build_catalog_slides_index() -> list[dict]:
    path = _resolve_catalog_file()
    if not path.exists() or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    items = raw.get("decks") if isinstance(raw, dict) and "decks" in raw else raw
    if isinstance(raw, dict) and "slides" in raw:
        items = raw.get("slides")
    if not isinstance(items, list):
        return []

    seen_slugs: set[str] = set()
    slides: list[dict] = []
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
        if not target_pdf.lower().endswith(".pdf"):
            target_pdf += ".pdf"
        name = (
            str(entry.get("name") or "").strip()
            or str(entry.get("title") or "").strip()
            or Path(target_pdf).stem
        )
        if not _is_displayable_slide_name(name):
            continue
        explicit_slug = str(entry.get("slug") or "").strip().lower()
        slug = explicit_slug or _slugify(Path(target_pdf).stem)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        slides.append({
            "name": name,
            "slug": slug,
            "url": f"/api/slides/file/{slug}",
            "updated_at": None,
            "source": "catalog",
        })
    return slides


def _uploaded_slides_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".server-data") / "uploaded-slides"


def _uploaded_slide_meta_path(slug: str) -> Path:
    return _uploaded_slides_dir() / f"{slug}.json"


def _server_materials_dir() -> Path:
    configured = os.environ.get("SERVER_MATERIALS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("server_materials")


def _normalize_relative_material_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(status_code=400, detail="relative_path is required")
    pure = Path(raw)
    if pure.is_absolute():
        raise HTTPException(status_code=400, detail="relative_path must be relative")
    parts = [part for part in pure.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="relative_path cannot contain '..'")
    if not parts:
        raise HTTPException(status_code=400, detail="relative_path is required")
    return "/".join(parts)


def _material_target_path(relative_path: str) -> Path:
    root = _server_materials_dir()
    target = root / relative_path
    try:
        root_resolved = root.resolve()
        target_resolved = target.resolve()
    except FileNotFoundError:
        # Parent may not exist yet; resolve lexical path safely.
        root_resolved = root.resolve()
        target_resolved = (root / relative_path).resolve(strict=False)
    if root_resolved not in target_resolved.parents and target_resolved != root_resolved:
        raise HTTPException(status_code=400, detail="Invalid relative_path")
    return target
def _build_local_slides_index() -> tuple[list[dict], dict[str, Path]]:
    slides_dir = _resolve_local_slides_dir()
    if not slides_dir:
        return [], {}

    files = sorted(
        [p for p in slides_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=lambda p: p.name.lower(),
    )
    seen_slugs: set[str] = set()
    slides: list[dict] = []
    by_slug: dict[str, Path] = {}
    for idx, pdf in enumerate(files):
        if not _is_displayable_slide_name(pdf.stem):
            continue
        base_slug = _slugify(pdf.stem)
        slug = base_slug
        while slug in seen_slugs:
            slug = f"{base_slug}-{idx+1}"
        seen_slugs.add(slug)
        mtime = datetime.fromtimestamp(pdf.stat().st_mtime, tz=timezone.utc).isoformat()
        slides.append({
            "name": pdf.stem,
            "slug": slug,
            "url": f"/api/slides/file/{slug}",
            "updated_at": mtime,
            "source": "local_materials",
        })
        by_slug[slug] = pdf
    return slides, by_slug


def _build_uploaded_slides_index() -> tuple[list[dict], dict[str, Path]]:
    slides_dir = _uploaded_slides_dir()
    if not slides_dir.exists() or not slides_dir.is_dir():
        return [], {}
    files = sorted(
        [p for p in slides_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=lambda p: p.name.lower(),
    )
    slides: list[dict] = []
    by_slug: dict[str, Path] = {}
    for pdf in files:
        slug = _slugify(pdf.stem)
        meta_name = None
        meta_path = _uploaded_slide_meta_path(slug)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta_name = str(meta.get("name") or "").strip()
            except Exception:
                meta_name = None
        display_name = meta_name or pdf.stem
        if not _is_displayable_slide_name(display_name):
            continue
        updated = datetime.fromtimestamp(pdf.stat().st_mtime, tz=timezone.utc).isoformat()
        slides.append({
            "name": display_name,
            "slug": slug,
            "url": f"/api/slides/file/{slug}",
            "updated_at": updated,
            "source": "uploaded",
        })
        by_slug[slug] = pdf
    return slides, by_slug


def _merge_slide_sources(
    state_slides: list[dict],
    local_slides: list[dict],
    uploaded_slides: list[dict],
    catalog_slides: list[dict],
) -> list[dict]:
    merged: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for source in (uploaded_slides, local_slides, state_slides, catalog_slides):
        for entry in source:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            url = str(entry.get("url") or "").strip()
            if not _is_displayable_slide_name(name) or not url:
                continue
            slug = str(entry.get("slug") or _slugify(name)).strip() or _slugify(name)
            pair = (slug, url)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            merged.append({
                "name": name,
                "slug": slug,
                "url": url,
                "updated_at": entry.get("updated_at"),
                "etag": entry.get("etag"),
                "last_modified": entry.get("last_modified"),
                "source": entry.get("source"),
            })
    return merged


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


def _resolve_slide_path(slug: str) -> Path | None:
    _, local_index = _build_local_slides_index()
    _, uploaded_index = _build_uploaded_slides_index()
    return local_index.get(slug) or uploaded_index.get(slug)


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


@router.post("/api/materials/upsert")
async def upsert_material_file(
    relative_path: str = Form(...),
    file: UploadFile = File(...),
):
    rel = _normalize_relative_material_path(relative_path)
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file upload")

    target = _material_target_path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)

    return {
        "ok": True,
        "relative_path": rel,
        "size": len(body),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/materials/delete")
async def delete_material_file(body: MaterialsDeleteRequest):
    rel = _normalize_relative_material_path(body.relative_path)
    target = _material_target_path(rel)
    existed = target.exists()
    if target.exists() and target.is_file():
        target.unlink()

    # Clean up empty directories up to materials root.
    root = _server_materials_dir().resolve()
    parent = target.parent
    while True:
        try:
            parent_resolved = parent.resolve()
        except Exception:
            break
        if parent_resolved == root:
            break
        if parent_resolved.exists() and parent_resolved.is_dir() and not any(parent_resolved.iterdir()):
            parent_resolved.rmdir()
            parent = parent_resolved.parent
            continue
        break

    return {"ok": True, "relative_path": rel, "deleted": bool(existed)}


@router.post("/api/slides/upload")
async def upload_slide_pdf(
    file: UploadFile = File(...),
    slug: str | None = Form(default=None),
    name: str | None = Form(default=None),
):
    incoming_name = (file.filename or "slide.pdf").strip()
    if not incoming_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted")

    target_slug = _slugify(slug or Path(incoming_name).stem)
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file upload")

    store_dir = _uploaded_slides_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = store_dir / f"{target_slug}.pdf"
    target_pdf.write_bytes(body)

    display_name = str(name or Path(incoming_name).stem or target_slug).strip()
    if not _is_displayable_slide_name(display_name):
        display_name = target_slug
    meta = {
        "name": display_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _uploaded_slide_meta_path(target_slug).write_text(json.dumps(meta), encoding="utf-8")

    slide = {
        "name": display_name,
        "slug": target_slug,
        "url": f"/api/slides/file/{target_slug}",
        "updated_at": meta["updated_at"],
        "source": "uploaded",
    }
    return {"ok": True, "slide": slide}


@router.post("/api/slides/current")
async def set_current_slides(body: SlidesUpdate):
    state.slides_current = {
        "url": body.url,
        "slug": body.slug,
        "source_file": body.source_file,
        "converter": body.converter,
        "updated_at": body.updated_at or datetime.now(timezone.utc).isoformat(),
    }
    await broadcast_state()
    return {"ok": True, "slides_current": state.slides_current}


@router.delete("/api/slides/current")
async def clear_current_slides():
    state.slides_current = None
    await broadcast_state()
    return {"ok": True}


@router.get("/api/slides/catalog-map")
async def get_slides_catalog_map():
    path = _resolve_catalog_file()
    return {
        "catalog_file": str(path),
        "entries": _load_catalog_map_entries(path),
    }


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


@public_router.get("/api/slides/current")
async def get_current_slides():
    return {"slides_current": state.slides_current}


@public_router.get("/api/slides")
async def get_slides():
    local_slides, _ = _build_local_slides_index()
    uploaded_slides, _ = _build_uploaded_slides_index()
    catalog_slides = _build_catalog_slides_index()
    state_slides = list(state.slides or [])
    current = state.slides_current or {}
    if current.get("url"):
        state_slides.append({
            "name": current.get("source_file") or "Current Slides",
            "slug": current.get("slug") or _slugify(current.get("source_file") or "current-slides"),
            "url": current["url"],
            "updated_at": current.get("updated_at"),
            "source": "slides_current",
        })
    slides = _merge_slide_sources(state_slides, local_slides, uploaded_slides, catalog_slides)
    return {"slides": slides}


@public_router.api_route("/api/slides/file/{slug}", methods=["GET", "HEAD"])
async def get_slide_file(slug: str, request: Request):
    path = _resolve_slide_path(slug)
    if path is None:
        if not _on_demand_enabled():
            raise HTTPException(status_code=404, detail="Slide not found")
        if state.daemon_ws is None:
            raise HTTPException(status_code=503, detail="Slides service temporarily unavailable.")
        path = await _wait_for_slide_upload(slug)

    etag = _slide_etag(path)
    headers = {
        "ETag": etag,
        "Last-Modified": _slide_last_modified(path),
        "Cache-Control": "public, max-age=86400, must-revalidate",
    }
    if _is_not_modified(request, etag, path):
        return Response(status_code=304, headers=headers)
    return FileResponse(path=path, media_type="application/pdf", filename=path.name, headers=headers)
