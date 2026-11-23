"""Which slides of a deck changed between two saves, read from the .pptx itself.

A .pptx is a zip whose directory already holds a CRC per file, so a fingerprint per slide
costs a few milliseconds and no extraction: the slide's own XML, its relationships, and the
pictures and charts it points to. Speaker notes are left out: they are not on the slide.
Used by local_publish.py to print only the slides a save changed.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel

_SLIDE_ID = re.compile(r'<p:sldId\b[^>]*?\bid="(\d+)"[^>]*?\br:id="([^"]+)"')
_RELATIONSHIP = re.compile(r"<Relationship\b[^>]*>")
_ATTR = re.compile(r'\b(Id|Target|Type|TargetMode)="([^"]*)"')
_SLIDE_SIZE = re.compile(r'<p:sldSz\b[^>]*?\bcx="(\d+)"[^>]*?\bcy="(\d+)"')
# "Hide Slide" is an attribute of the slide's root element, which opens the file.
_HIDDEN = re.compile(rb'<p:sld\b[^>]*?\bshow="(?:0|false)"')
_ROOT_TAG_WITHIN = 4096
# What every slide is drawn on: a change here can move anything on any slide.
_SHARED_PARTS = ("ppt/slideLayouts/", "ppt/slideMasters/", "ppt/theme/")
_NOT_ON_THE_SLIDE = ("notesSlide", "comments", "slideLayout")


class DeckFingerprint(BaseModel):
    """A deck as of one save: enough to tell which slides the next save changed."""

    slides: list[tuple[str, str]]  # (PowerPoint's own slide id, digest), in deck order
    shared: str                    # layouts, masters and theme
    aspect: float                  # width / height of a slide


def _relationships(xml: str) -> list[dict[str, str]]:
    return [dict(_ATTR.findall(tag)) for tag in _RELATIONSHIP.findall(xml)]


def fingerprint(pptx: Path) -> DeckFingerprint:
    with zipfile.ZipFile(pptx) as deck:
        crc = {info.filename: info.CRC for info in deck.infolist()}
        presentation = deck.read("ppt/presentation.xml").decode("utf-8")
        targets = {
            rel["Id"]: rel["Target"]
            for rel in _relationships(deck.read("ppt/_rels/presentation.xml.rels").decode("utf-8"))
            if "Id" in rel and "Target" in rel
        }
        slides: list[tuple[str, str]] = []
        for slide_id, rel_id in _SLIDE_ID.findall(presentation):
            part = posixpath.normpath(posixpath.join("ppt", targets[rel_id]))
            rels_part = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            digest = [f"{crc[part]:08x}"]
            if rels_part in crc:
                for rel in _relationships(deck.read(rels_part).decode("utf-8")):
                    kind = rel.get("Type", "").rsplit("/", 1)[-1]
                    if kind in _NOT_ON_THE_SLIDE:
                        continue
                    target = rel.get("Target", "")
                    if rel.get("TargetMode") == "External":
                        digest.append(f"{kind}:{target}")  # a link's address
                        continue
                    linked = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
                    digest.append(f"{kind}:{crc.get(linked, 0):08x}")
            slides.append((slide_id, "|".join(sorted(digest[1:])) + "#" + digest[0]))
        shared = "|".join(f"{name}:{crc[name]:08x}" for name in sorted(crc) if name.startswith(_SHARED_PARTS))
        size = _SLIDE_SIZE.search(presentation)
        aspect = int(size.group(1)) / int(size.group(2)) if size else 16 / 9
    return DeckFingerprint(slides=slides, shared=shared, aspect=aspect)


def hidden_slides(pptx: Path) -> list[int]:
    """The 1-based positions of the slides marked "Hide Slide". PowerPoint's print leaves
    them out, so a printed deck has fewer pages than the deck has slides."""
    with zipfile.ZipFile(pptx) as deck:
        presentation = deck.read("ppt/presentation.xml").decode("utf-8")
        targets = {
            rel["Id"]: rel["Target"]
            for rel in _relationships(deck.read("ppt/_rels/presentation.xml.rels").decode("utf-8"))
            if "Id" in rel and "Target" in rel
        }
        hidden: list[int] = []
        for position, (_, rel_id) in enumerate(_SLIDE_ID.findall(presentation), start=1):
            part = posixpath.normpath(posixpath.join("ppt", targets[rel_id]))
            with deck.open(part) as slide:
                if _HIDDEN.search(slide.read(_ROOT_TAG_WITHIN)):
                    hidden.append(position)
    return hidden


def slide_version(digest: str) -> str:
    """A short, fixed-length name for one version of a slide (its digest lists links)."""
    return hashlib.sha1(digest.encode()).hexdigest()[:20]


def changed_positions(before: DeckFingerprint | None, after: DeckFingerprint) -> list[int] | None:
    """The 1-based positions of the slides that differ, or None when the deck has to be
    printed whole: no earlier save to compare with, slides added, removed or moved, or the
    layouts every slide is drawn on changed."""
    if before is None or before.shared != after.shared or before.aspect != after.aspect:
        return None
    if [slide_id for slide_id, _ in before.slides] != [slide_id for slide_id, _ in after.slides]:
        return None
    return [i + 1 for i, (old, new) in enumerate(zip(before.slides, after.slides)) if old != new]


def as_ranges(positions: list[int]) -> list[tuple[int, int]]:
    """[2, 3, 4, 9] → [(2, 4), (9, 9)]: one print job per run of neighbouring slides."""
    ranges: list[tuple[int, int]] = []
    for position in sorted(set(positions)):
        if ranges and position == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], position)
        else:
            ranges.append((position, position))
    return ranges
