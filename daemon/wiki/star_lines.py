"""Each note's star count written at the foot of its markdown (`- ⭐ 4`), so the vault
itself shows which notes were hot for the room, in Obsidian and in the session folder
handed out after the workshop (Victor, 2026-11-10).

wiki-stars.json stays the source of truth: the line is a mirror, rewritten whenever a
count changes and put back after the summarizer rewrites a note. A note nobody starred
has no line. The built site never shows it (its graph has live counts): the build strips
it, and the vault's fingerprint ignores it, so a star never costs a Quartz build.

Only a note whose line is off gets written, in place (no rename: Google Drive keeps the
file and its history), and only if nothing touched it since it was read.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from daemon import log

_STAR_LINE = re.compile(r"\n?- ⭐ \d+\s*\Z")


def note_slug(rel: str) -> str:
    """Quartz's slug for a vault note: its path without .md, spaces as dashes. NFC, since a
    macOS folder may hand back the decomposed é the browser never sends."""
    return unicodedata.normalize("NFC", rel.removesuffix(".md").replace(" ", "-"))


def strip_star_line(text: str) -> str:
    return _STAR_LINE.sub("\n", text) if _STAR_LINE.search(text) else text


def with_star_line(text: str, stars: int) -> str:
    """The note ending in `- ⭐ <stars>`, or without that line when nobody starred it."""
    bare = strip_star_line(text)
    if not stars:
        return bare
    return f"{bare.rstrip()}\n- ⭐ {stars}\n"


def notes(wiki_dir: Path):
    """(path, slug) of every note of the vault, outside Obsidian's settings."""
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir).as_posix()
        if not any(part == ".obsidian" or part.startswith("~$") for part in rel.split("/")):
            yield path, note_slug(rel)


def sync_star_lines(wiki_dir: Path, counts: dict[str, int]) -> int:
    """Bring every note's star line in line with counts; how many notes were rewritten."""
    written = 0
    for path, slug in notes(wiki_dir):
        try:
            before = path.stat().st_mtime_ns
            text = path.read_text(encoding="utf-8")
            wanted = with_star_line(text, counts.get(slug, 0))
            if wanted == text or path.stat().st_mtime_ns != before:
                continue  # already right, or being written by someone else: next round
            path.write_text(wanted, encoding="utf-8")
            written += 1
        except (OSError, UnicodeDecodeError) as e:
            log.error("wiki", f"Star line not written to {path.name}: {e}")
    return written
