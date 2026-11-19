"""What happens to the pages PowerPoint printed before they are sent: cut the paper's
white margins off, shrink the pictures, and put changed pages into the deck.

PowerPoint prints a slide in the middle of the printer's paper (A4), so every page of a
print job has the slide at the same place: `slide_box` finds it once, on a whole-deck
print, and `crop` cuts every later page to it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

Box = tuple[float, float, float, float]  # left, bottom, right, top, in points

_BBOX = re.compile(r"%%HiResBoundingBox: ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)")
# Below this many pages one Ghostscript is quicker than splitting the job.
_PARALLEL_FROM_PAGES = 24
_GS_TIMEOUT_S = 180
# Enough pages to meet a slide that reaches its corners; all 119 take 25 s to measure.
_BOX_FROM_PAGES = 15

# Quartz writes PDFs whose table of objects has harmless gaps; pypdf says so once per gap.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class PdfToolError(RuntimeError):
    """Ghostscript is missing or failed."""


def _gs() -> str:
    path = shutil.which("gs") or "/opt/homebrew/bin/gs"
    if not Path(path).exists():
        raise PdfToolError("Ghostscript (gs) is not installed: brew install ghostscript")
    return path


def slide_box(printed: Path) -> Box:
    """Where the slides sit on the printed pages: the smallest box holding the ink of
    its first pages. Exact as soon as one of them has a background or anything in two
    opposite corners; the caller checks it has the deck's shape."""
    result = subprocess.run(
        [_gs(), "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=bbox", f"-dLastPage={_BOX_FROM_PAGES}", str(printed)],
        capture_output=True, text=True, timeout=_GS_TIMEOUT_S,
    )
    boxes = [tuple(map(float, m.groups())) for m in _BBOX.finditer(result.stderr + result.stdout)]
    boxes = [b for b in boxes if b[2] > b[0] and b[3] > b[1]]
    if not boxes:
        raise PdfToolError("The printed pages are empty")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def matches_aspect(box: Box, aspect: float, tolerance: float = 0.02) -> bool:
    return abs((box[2] - box[0]) / (box[3] - box[1]) - aspect) <= tolerance * aspect


def crop(printed: Path, box: Box, out: Path) -> int:
    """Every page cut down to `box`. Returns the number of pages."""
    reader = PdfReader(str(printed))
    writer = PdfWriter()
    rect = RectangleObject(list(box))
    for page in reader.pages:
        for name in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
            setattr(page, name, rect)
        writer.add_page(page)
    with open(out, "wb") as target:
        writer.write(target)
    return len(reader.pages)


def _compress_range(source: Path, out: Path, first: int | None = None, last: int | None = None) -> subprocess.Popen:
    pages = [f"-dFirstPage={first}", f"-dLastPage={last}"] if first else []
    return subprocess.Popen(
        [_gs(), "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/ebook",
         "-dDetectDuplicateImages=true", *pages, f"-sOutputFile={out}", str(source)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def compress(source: Path, out: Path, pages: int) -> None:
    """Pictures resampled for a screen (PowerPoint embeds every emoji as a picture).
    A whole deck is done in chunks on several cores: 8 s instead of 45."""
    if pages < _PARALLEL_FROM_PAGES:
        if _compress_range(source, out).wait(timeout=_GS_TIMEOUT_S) != 0:
            raise PdfToolError("Ghostscript failed to compress the pages")
        return
    chunks = min(10, max(2, (os.cpu_count() or 4) // 2))
    with tempfile.TemporaryDirectory(prefix="slides-compress-") as tmp:
        jobs = []
        for i in range(chunks):
            first, last = i * pages // chunks + 1, (i + 1) * pages // chunks
            part = Path(tmp) / f"part-{i:02d}.pdf"
            jobs.append((part, _compress_range(source, part, first, last)))
        writer = PdfWriter()
        for part, job in jobs:
            if job.wait(timeout=_GS_TIMEOUT_S) != 0:
                raise PdfToolError("Ghostscript failed to compress the deck")
            writer.append(str(part))
        with open(out, "wb") as target:
            writer.write(target)


def replace_pages(deck: Path, pages_pdf: Path, positions: list[int], out: Path) -> None:
    """The deck with its pages at `positions` (1-based) replaced by the pages of
    `pages_pdf`, in that order. Mirrors railway/features/slides/pages.py."""
    current = PdfReader(str(deck))
    new = PdfReader(str(pages_pdf))
    if len(new.pages) != len(positions) or not all(1 <= p <= len(current.pages) for p in positions):
        raise ValueError(f"{len(new.pages)} pages for positions {positions} of a {len(current.pages)}-page deck")
    replacement = dict(zip(positions, new.pages))
    writer = PdfWriter()
    for number, page in enumerate(current.pages, start=1):
        writer.add_page(replacement.get(number, page))
    with open(out, "wb") as target:
        writer.write(target)
