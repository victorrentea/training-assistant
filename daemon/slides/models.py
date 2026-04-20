"""Shared Pydantic models for slide-related API and WS contracts."""
from enum import Enum

from pydantic import BaseModel


class SlideCacheStatus(str, Enum):
    not_cached = "not_cached"
    cached = "cached"
    downloading = "downloading"
    download_failed = "download_failed"


class Slide(BaseModel):
    status: SlideCacheStatus
    size_bytes: int | None = None
    downloaded_at: str | None = None
    modified_at: str | None = None
    title: str | None = None
    name: str | None = None
    error: str | None = None


class CurrentSlide(BaseModel):
    slug: str
    page: int


class SlidesLogEntry(BaseModel):
    file: str
    slide: int
    seconds_spent: float
    timestamp: str | None = None


class SlidesHistoryResponse(BaseModel):
    slides_log: list[SlidesLogEntry]
