"""Merge incoming slides_viewed deltas into the accumulated list."""
from __future__ import annotations

from datetime import datetime, timezone


def merge_slides_viewed(
    existing: list[dict],
    incoming: list[dict],
    slug_for_filename: dict[str, str] | None = None,
    timeline: list[dict] | None = None,
) -> None:
    """Merge incoming delta entries into existing list, in place.

    For each incoming entry:
      - If (slug, page) exists in existing, add seconds to it.
      - Otherwise, append a new entry.
      - If `timeline` is given, append a stamped moment to it as well.

    The totals in `existing` say which slides got airtime; the timeline says
    *when* each of them held the screen, which is the half a summary needs to
    attribute a paragraph of transcript to a slide number. Deck slides get
    renumbered between runs of a course, so the slide number is only meaningful
    next to the moment it was on screen.

    Args:
        existing: The current slides_viewed list (mutated in place).
        incoming: Delta entries with keys: fileName, page, seconds.
        slug_for_filename: Optional reverse map from PPTX filename to slug.
        timeline: Optional append-only list of {slug, page, seconds, at}.
    """
    slug_for_filename = slug_for_filename or {}
    index: dict[tuple[str, int], int] = {}
    for i, sv in enumerate(existing):
        key = (sv["slug"], sv["page"])
        index[key] = i

    for entry in incoming:
        file_name = entry.get("fileName", "")
        page = entry.get("page", 0)
        seconds = entry.get("seconds", 0)
        if not file_name or not page or seconds <= 0:
            continue
        slug = slug_for_filename.get(file_name) or slug_for_filename.get(
            file_name.removesuffix(".pptx").removesuffix(".ppt")
        ) or ""
        if not slug:
            continue
        key = (slug, page)
        now = datetime.now(tz=timezone.utc).isoformat()
        if timeline is not None:
            timeline.append({"slug": slug, "page": page, "seconds": seconds, "at": now})
        if key in index:
            existing[index[key]]["seconds"] += seconds
            existing[index[key]]["last_seen_at"] = now
        else:
            index[key] = len(existing)
            existing.append({"slug": slug, "page": page, "seconds": seconds, "last_seen_at": now})
