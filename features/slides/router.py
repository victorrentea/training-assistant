import json
import logging
import os
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from core.messaging import broadcast, broadcast_state
from core.state import state
from features.slides.upload import (
    SlidesUpdate,
    _is_displayable_slide_name,
    _local_slide_meta_path,
    _read_local_slide_source_updated_at,
    _slugify,
    _uploaded_slide_meta_path,
    _uploaded_slides_dir,
    router as upload_router,
)

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)

# Include sub-routers so that main.py only needs to include slides.router / slides.public_router.
router.include_router(upload_router)


def _resolve_catalog_file() -> Path:
    configured = os.environ.get("PPTX_CATALOG_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent.parent / "daemon" / "materials_slides_catalog.json"


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
        source_str = str(entry.get("source") or "").strip()
        updated_at = None
        if source_str:
            try:
                sp = Path(source_str).expanduser()
                if sp.exists() and sp.is_file():
                    updated_at = datetime.fromtimestamp(sp.stat().st_mtime, tz=timezone.utc).isoformat()
            except Exception:
                pass
        # Fall back to daemon-reported PPTX mtime from slides_catalog
        if not updated_at:
            cat_entry = state.slides_catalog.get(slug)
            if cat_entry:
                updated_at = cat_entry.get("updated_at")
        slides.append({
            "name": name,
            "slug": slug,
            "url": f"/api/slides/file/{slug}",
            "updated_at": updated_at,
            "group": str(entry.get("group") or "").strip() or None,
            "source": "catalog",
        })
    return slides


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
        source_updated_at = _read_local_slide_source_updated_at(slug)
        slides.append({
            "name": pdf.stem,
            "slug": slug,
            "url": f"/api/slides/file/{slug}",
            "updated_at": source_updated_at or mtime,
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
            participant_url = url
            if participant_url.startswith(("http://", "https://")):
                # Serve external URLs through local endpoint to enforce inline PDF rendering.
                participant_url = f"/api/slides/file/{slug}"
            merged.append({
                "name": name,
                "slug": slug,
                "url": participant_url,
                "updated_at": entry.get("updated_at"),
                "etag": entry.get("etag"),
                "last_modified": entry.get("last_modified"),
                "sync_status": entry.get("sync_status"),
                "sync_message": entry.get("sync_message"),
                "source": entry.get("source"),
                "group": entry.get("group"),
            })
    return merged


def _order_participant_slides_by_catalog(slides: list[dict], catalog_slides: list[dict]) -> list[dict]:
    catalog_order: dict[str, int] = {}
    for idx, entry in enumerate(catalog_slides):
        slug = str(entry.get("slug") or "").strip()
        if slug and slug not in catalog_order:
            catalog_order[slug] = idx

    def _sort_key(entry: dict) -> tuple:
        slug = str(entry.get("slug") or "").strip()
        if slug in catalog_order:
            return (0, catalog_order[slug], str(entry.get("name") or "").lower(), slug)
        return (1, str(entry.get("name") or "").lower(), slug)

    return sorted(slides, key=_sort_key)


def _collect_participant_slides(*, include_unavailable_when_daemon_offline: bool = False) -> list[dict]:
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
    merged = _merge_slide_sources(state_slides, local_slides, uploaded_slides, catalog_slides)
    ordered = _order_participant_slides_by_catalog(merged, catalog_slides)
    if include_unavailable_when_daemon_offline:
        return ordered
    # Keep full catalog visibility for participants; missing files are fetched on-demand via daemon WS.
    return ordered


def _display_name_or_slug(name: str, slug: str) -> str:
    cleaned_name = str(name or "").strip()
    cleaned_slug = str(slug or "").strip()
    if _is_displayable_slide_name(cleaned_name):
        return cleaned_name
    if _is_displayable_slide_name(cleaned_slug):
        return cleaned_slug
    return "Unnamed slide"


def _resolve_slide_path(slug: str) -> Path | None:
    _, local_index = _build_local_slides_index()
    _, uploaded_index = _build_uploaded_slides_index()
    return local_index.get(slug) or uploaded_index.get(slug)


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


@router.post("/api/slides/current")
async def set_current_slides(body: SlidesUpdate):
    state.slides_current = {
        "url": body.url,
        "slug": body.slug,
        "source_file": body.source_file,
        "presentation_name": body.presentation_name,
        "current_page": body.current_page,
        "converter": body.converter,
        "updated_at": body.updated_at or datetime.now(timezone.utc).isoformat(),
    }
    await broadcast_state()
    await broadcast({"type": "slides_current", "slides_current": state.slides_current})
    return {"ok": True, "slides_current": state.slides_current}


@router.delete("/api/slides/current")
async def clear_current_slides():
    state.slides_current = None
    await broadcast_state()
    await broadcast({"type": "slides_current", "slides_current": None})
    return {"ok": True}


@router.get("/api/slides/catalog-map")
async def get_slides_catalog_map():
    path = _resolve_catalog_file()
    return {
        "catalog_file": str(path),
        "entries": _load_catalog_map_entries(path),
    }


@public_router.get("/api/slides/current")
async def get_current_slides():
    return {"slides_current": state.slides_current}


@public_router.get("/api/slides")
async def get_slides():
    from features.slides.cache import _cache_path
    slides = _collect_participant_slides()
    _, local_index = _build_local_slides_index()
    _, uploaded_index = _build_uploaded_slides_index()
    for slide in slides:
        slug = str(slide.get("slug") or "")
        has_local_pdf = bool(local_index.get(slug) or uploaded_index.get(slug))
        in_cache = _cache_path(slug).exists()
        in_catalog = slug in state.slides_catalog
        is_catalog_source = slide.get("source") == "catalog"  # has GDrive URL, on-demand fetch works
        slide["available_on_server"] = has_local_pdf or in_cache or in_catalog or is_catalog_source
    return {"slides": slides}


@public_router.api_route("/api/slides/file/{slug}", methods=["GET", "HEAD"])
async def get_slide_file(slug: str, request: Request):
    from features.slides.cache import _cache_path, download_or_wait_cached

    # 1. Check local / uploaded
    path = _resolve_slide_path(slug)

    # 2. Check cache dir
    if not path:
        cached = _cache_path(slug)
        if cached.exists():
            path = cached

    # 3. On-demand GDrive download
    if not path:
        path = await download_or_wait_cached(slug)

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
