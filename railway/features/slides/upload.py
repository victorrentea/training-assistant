import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from railway.features.slides.cache import broadcast_slides_cache_status

router = APIRouter()

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _is_displayable_slide_name(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    return any(ch.isalnum() for ch in cleaned)


def _uploaded_slides_dir() -> Path:
    configured = os.environ.get("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(".server-data") / "uploaded-slides"


def _uploaded_slide_meta_path(slug: str) -> Path:
    return _uploaded_slides_dir() / f"{slug}.json"
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
    await broadcast_slides_cache_status()

    slide = {
        "name": display_name,
        "slug": target_slug,
        "url": f"/api/slides/file/{target_slug}",
        "updated_at": meta["updated_at"],
        "source": "uploaded",
    }
    return {"ok": True, "slide": slide}
