import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from core.messaging import broadcast

router = APIRouter()

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _is_displayable_slide_name(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    return any(ch.isalnum() for ch in cleaned)


class SlidesUpdate(BaseModel):
    url: str
    slug: str
    source_file: str | None = None
    presentation_name: str | None = None
    current_page: int | None = None
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

    @field_validator("current_page")
    @classmethod
    def validate_current_page(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1:
            raise ValueError("current_page must be >= 1")
        return value


class MaterialsDeleteRequest(BaseModel):
    relative_path: str


def _uploaded_slides_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".server-data") / "uploaded-slides"


def _uploaded_slide_meta_path(slug: str) -> Path:
    return _uploaded_slides_dir() / f"{slug}.json"


def _local_slides_meta_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_LOCAL_SLIDES_META_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".server-data") / "local-slides-meta"


def _local_slide_meta_path(slug: str) -> Path:
    return _local_slides_meta_dir() / f"{slug}.json"


def _read_local_slide_source_updated_at(slug: str) -> str | None:
    path = _local_slide_meta_path(slug)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    updated = str(raw.get("source_updated_at") or "").strip()
    return updated or None


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


@router.post("/api/materials/upsert")
async def upsert_material_file(
    relative_path: str = Form(...),
    source_mtime: str | None = Form(default=None),
    file: UploadFile = File(...),
):
    rel = _normalize_relative_material_path(relative_path)
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file upload")

    target = _material_target_path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    source_updated_at = None
    parsed_source_mtime = None
    if source_mtime is not None and source_mtime.strip():
        try:
            parsed_source_mtime = float(source_mtime)
            source_updated_at = datetime.fromtimestamp(parsed_source_mtime, tz=timezone.utc).isoformat()
        except ValueError:
            parsed_source_mtime = None
            source_updated_at = None

    if rel.startswith("slides/") and target.suffix.lower() == ".pdf":
        slug = _slugify(Path(rel).stem)
        meta_dir = _local_slides_meta_dir()
        meta_dir.mkdir(parents=True, exist_ok=True)
        _local_slide_meta_path(slug).write_text(
            json.dumps(
                {
                    "relative_path": rel,
                    "source_mtime": parsed_source_mtime,
                    "source_updated_at": source_updated_at,
                }
            ),
            encoding="utf-8",
        )
        effective_updated_at = source_updated_at or datetime.now(timezone.utc).isoformat()
        await broadcast({"type": "slides_updated", "slug": slug, "updated_at": effective_updated_at})

    return {
        "ok": True,
        "relative_path": rel,
        "size": len(body),
        "updated_at": source_updated_at or datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/materials/delete")
async def delete_material_file(body: MaterialsDeleteRequest):
    rel = _normalize_relative_material_path(body.relative_path)
    target = _material_target_path(rel)
    existed = target.exists()
    if target.exists() and target.is_file():
        target.unlink()
    if rel.startswith("slides/") and target.suffix.lower() == ".pdf":
        slug = _slugify(Path(rel).stem)
        _local_slide_meta_path(slug).unlink(missing_ok=True)

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
    await broadcast({"type": "slides_updated", "slug": target_slug, "updated_at": meta["updated_at"]})

    slide = {
        "name": display_name,
        "slug": target_slug,
        "url": f"/api/slides/file/{target_slug}",
        "updated_at": meta["updated_at"],
        "source": "uploaded",
    }
    return {"ok": True, "slide": slide}
