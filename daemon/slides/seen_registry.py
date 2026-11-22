"""Which slides a session showed, in the form they were shown: the rules, no I/O.

Victor Mac reports a slide once it has stayed on screen 7 s with PowerPoint in front
(`qualified`) and again when he moves on (`closed`); the deck is saved on disk by then.
A slide is one deck file + PowerPoint's own slide id (`<p:sldId id>`, which survives
moving the slide), so the same content copied into another deck counts again (Victor,
2026-11-22). Its version is `pptx_slides.slide_version` of the per-slide digest: the
slide's XML and what it links to, without the layouts and theme, so a new theme only
updates the slides shown again.

  - a slide not seen before is appended (pages are in the order of first showing);
  - shown again unchanged: nothing;
  - shown again changed: the new version replaces the old one in place.

`version` is the version last shown; `page` the version whose page the deck holds. They
differ while the page of a new version is not printed yet.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Change = Literal["added", "updated"]


class SeenSlide(BaseModel):
    deck_path: str
    deck: str  # file name, for the trainer's toast and the logs
    slide_id: str
    version: str  # pptx_slides.slide_version of the version last shown
    page: str | None = None
    first_seen: str
    last_seen: str


class SeenRegistry(BaseModel):
    session_id: str
    slides: list[SeenSlide] = []
    # When the assembled deck last changed: participants cache the PDF under it.
    updated_at: str | None = None


def page_file_name(version: str) -> str:
    return f"{version}.pdf"


def find(registry: SeenRegistry, deck_path: str, slide_id: str) -> SeenSlide | None:
    return next((s for s in registry.slides if s.deck_path == deck_path and s.slide_id == slide_id), None)


def record(registry: SeenRegistry, deck_path: str, deck: str, slide_id: str, version: str, at: str) -> Change | None:
    """Note one showing. Returns what changed in the session's seen deck, if anything."""
    slide = find(registry, deck_path, slide_id)
    if slide is None:
        registry.slides.append(SeenSlide(deck_path=deck_path, deck=deck, slide_id=slide_id, version=version,
                                         first_seen=at, last_seen=at))
        return "added"
    slide.last_seen = at
    slide.deck = deck
    if slide.version == version:
        return None
    slide.version = version
    return "updated"


def pending(registry: SeenRegistry) -> list[SeenSlide]:
    """Slides whose last shown version has no page yet."""
    return [s for s in registry.slides if s.page != s.version]


def with_pages(registry: SeenRegistry) -> list[SeenSlide]:
    """The slides that make the deck, in order: those with a page of any version."""
    return [s for s in registry.slides if s.page is not None]
