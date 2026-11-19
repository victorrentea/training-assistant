"""A deck as PowerPoint prints it, sent by the daemon: whole, or only the pages a save
changed, which are put into the deck already held here.

The cache used to be filled only from Google Drive, whose conversion lays slides out
differently from PowerPoint on the trainer's Mac. See daemon/slides/local_publish.py.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter

MAX_DECK_BYTES = 80 * 1024 * 1024


class PagesDoNotFit(ValueError):
    """The pages sent do not match the positions, or the positions the deck."""


def replace_pages(deck: bytes, pages: bytes, positions: list[int]) -> bytes:
    """The deck with its pages at `positions` (1-based) replaced by `pages`, in that order."""
    current = PdfReader(io.BytesIO(deck))
    new = PdfReader(io.BytesIO(pages))
    if len(new.pages) != len(positions) or len(set(positions)) != len(positions):
        raise PagesDoNotFit(f"{len(new.pages)} pages for positions {positions}")
    if not all(1 <= p <= len(current.pages) for p in positions):
        raise PagesDoNotFit(f"positions {positions} outside a {len(current.pages)}-page deck")
    replacement = dict(zip(positions, new.pages))
    writer = PdfWriter()
    for number, page in enumerate(current.pages, start=1):
        writer.add_page(replacement.get(number, page))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def write_atomically(dest: Path, data: bytes) -> None:
    """Phones range-read this file during a talk: they must never see it half-written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
