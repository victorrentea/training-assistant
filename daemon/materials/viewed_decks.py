"""Pick the slide decks the session actually showed, for the materials zip.

The daemon only names them. Railway adds the PDFs from its own slides cache
(railway/features/materials/router.py), so no deck crosses the trainer's
uplink — and the PDFs on this disk are stale exports anyway: the current ones
are pulled from Google Drive by Railway.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from daemon.slides.catalog import _title_to_pdf_name

# A deck flipped through for a few seconds (bio, a wrong deck opened by
# mistake) is noise, not material.
MIN_DECK_SECONDS = 120


class ZipDeck(BaseModel):
    """One deck Railway should add to the zip, as `slides/<filename>`."""

    slug: str
    filename: str
    drive_export_url: str = ""


def select_viewed_decks(
    slides_viewed: list[dict],
    catalog: dict[str, dict],
    min_seconds: int = MIN_DECK_SECONDS,
) -> list[ZipDeck]:
    """Decks with at least `min_seconds` of airtime, most-viewed first."""
    seconds: dict[str, int] = defaultdict(int)
    for entry in slides_viewed:
        slug = entry.get("slug") or ""
        if slug:
            seconds[slug] += int(entry.get("seconds") or 0)

    ranked = sorted(
        (slug for slug, total in seconds.items() if total >= min_seconds and slug in catalog),
        key=lambda slug: -seconds[slug],
    )
    return [
        ZipDeck(
            slug=slug,
            filename=_title_to_pdf_name(str(catalog[slug].get("title") or slug)),
            drive_export_url=str(catalog[slug].get("drive_export_url") or ""),
        )
        for slug in ranked
    ]
