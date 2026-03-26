from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from messaging import broadcast_state
from state import state

router = APIRouter()
public_router = APIRouter()
_SLUG_RE = re.compile(r"[^a-z0-9]+")


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
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    # Expected local folder from request context.
    candidates.append(Path.home() / "workspace" / "training-assistant" / "materials" / "slides")
    # Alternate naming with spaces/casing.
    candidates.append(Path.home() / "Training Assistant" / "Materials" / "Slides")
    # Fallback to repo-local materials/slides when available.
    candidates.append(Path(__file__).resolve().parent.parent / "materials" / "slides")
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


def _uploaded_slides_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".context") / "uploaded-slides"


def _uploaded_slide_meta_path(slug: str) -> Path:
    return _uploaded_slides_dir() / f"{slug}.json"
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


def _merge_slide_sources(state_slides: list[dict], local_slides: list[dict], uploaded_slides: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for source in (uploaded_slides, local_slides, state_slides):
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


@public_router.get("/api/slides/current")
async def get_current_slides():
    return {"slides_current": state.slides_current}


@public_router.get("/api/slides")
async def get_slides():
    local_slides, _ = _build_local_slides_index()
    uploaded_slides, _ = _build_uploaded_slides_index()
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
    slides = _merge_slide_sources(state_slides, local_slides, uploaded_slides)
    return {"slides": slides}


@public_router.get("/api/slides/file/{slug}")
async def get_slide_file(slug: str):
    _, local_index = _build_local_slides_index()
    _, uploaded_index = _build_uploaded_slides_index()
    path = local_index.get(slug) or uploaded_index.get(slug)
    if path is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    return FileResponse(path=path, media_type="application/pdf", filename=path.name)
