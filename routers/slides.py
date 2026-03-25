from datetime import datetime, timezone
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
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


def _merge_slide_sources(state_slides: list[dict], local_slides: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for source in (local_slides, state_slides):
        for entry in source:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            url = str(entry.get("url") or "").strip()
            if not name or not url:
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


@public_router.get("/api/slides/current")
async def get_current_slides():
    return {"slides_current": state.slides_current}


@public_router.get("/api/slides")
async def get_slides():
    local_slides, _ = _build_local_slides_index()
    slides = _merge_slide_sources(state.slides, local_slides)
    return {"slides": slides}


@public_router.get("/api/slides/file/{slug}")
async def get_slide_file(slug: str):
    _, local_index = _build_local_slides_index()
    path = local_index.get(slug)
    if path is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    return FileResponse(path=path, media_type="application/pdf", filename=path.name)
