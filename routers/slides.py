from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from messaging import broadcast_state
from state import state

router = APIRouter()
public_router = APIRouter()


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
    return {"slides": state.slides}
