#!/usr/bin/env python3
"""Swap the see-through EMF pictures of a .pptx for PNGs, so Google's PDF export draws them right.

PowerPoint on the Mac pastes some pictures as an EMF that only wraps a bitmap with an alpha
channel (an EMF+ 32bpp ARGB/PARGB image). PowerPoint shows the transparent part as
transparent; Google Slides, which makes the PDF the participants' Slides tab shows, paints
it opaque white, hiding whatever lies under the picture (Microservices slide 84, bug report
of 24 Nov 2026). A PNG with the same pixels and the same alpha renders the same everywhere.

    scripts/fix_alpha_emf.py DECK.pptx...          # list what would change
    scripts/fix_alpha_emf.py --apply DECK.pptx...  # rewrite the decks in place

--apply refuses a deck that PowerPoint has open (its `~$` lock file sits beside it): the next
save in PowerPoint would put the EMF back. A copy of each original goes to
~/Library/Caches/training-assistant/pptx-backups/ first. Standard library only.
"""
from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import struct
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

_EMR_COMMENT = 70
_EMFPLUS_OBJECT = 0x4008
_OBJECT_IMAGE = 5
_IMAGE_BITMAP = 1
_BITMAP_PIXELS = 0  # uncompressed pixel data (1 would be an embedded PNG/JPEG)
_PARGB = 0x000E200B  # premultiplied alpha
_ARGB = 0x0026200A
_BACKUPS = Path.home() / "Library/Caches/training-assistant/pptx-backups"


def alpha_bitmap(emf: bytes) -> tuple[int, int, int, int, bytes] | None:
    """(width, height, stride, pixel format, pixels) of the alpha bitmap an EMF wraps, else None."""
    i = 0
    while i + 8 <= len(emf):
        kind, size = struct.unpack_from("<II", emf, i)
        if size == 0:
            break
        if kind == _EMR_COMMENT and emf[i + 12:i + 16] == b"EMF+":
            data_len = struct.unpack_from("<I", emf, i + 8)[0]
            j, end = i + 16, i + 12 + data_len
            while j + 12 <= end:
                rtype, flags, rsize, _ = struct.unpack_from("<HHII", emf, j)
                if rsize == 0:
                    break
                if rtype == _EMFPLUS_OBJECT and (flags >> 8) & 0x7F == _OBJECT_IMAGE:
                    # Continued objects (flag 0x8000) span records; not handled, so skipped.
                    if not flags & 0x8000 and struct.unpack_from("<I", emf, j + 16)[0] == _IMAGE_BITMAP:
                        w, h, stride, fmt, btype = struct.unpack_from("<iiiII", emf, j + 20)
                        if fmt in (_PARGB, _ARGB) and btype == _BITMAP_PIXELS and w > 0 and h > 0:
                            pixels = emf[j + 40:j + 40 + abs(stride) * h]
                            if len(pixels) == abs(stride) * h:
                                return w, h, stride, fmt, pixels
                j += rsize
        i += size
    return None


def to_png(w: int, h: int, stride: int, fmt: int, pixels: bytes) -> bytes:
    rows = []
    for y in range(h):
        row = pixels[y * abs(stride):y * abs(stride) + 4 * w]
        out = bytearray(4 * w)
        for x in range(w):
            b, g, r, a = row[4 * x:4 * x + 4]
            if fmt == _PARGB and 0 < a < 255:
                r, g, b = (min(255, c * 255 // a) for c in (r, g, b))
            out[4 * x:4 * x + 4] = bytes((r, g, b, a))
        rows.append(b"\x00" + bytes(out))
    if stride < 0:  # bottom-up rows
        rows.reverse()

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def plan(deck: zipfile.ZipFile) -> dict[str, bytes]:
    """media path of each alpha EMF -> the PNG to put in its place."""
    names = set(deck.namelist())
    swaps = {}
    for name in sorted(names):
        if name.startswith("ppt/media/") and name.lower().endswith(".emf"):
            found = alpha_bitmap(deck.read(name))
            if found:
                png = name[:-4] + ".png"
                if png not in names:
                    swaps[name] = to_png(*found)
    return swaps


def slides_using(deck: zipfile.ZipFile, media: str) -> list[str]:
    hits = []
    for name in deck.namelist():
        if name.endswith(".rels") and "/_rels/" in name:
            owner_dir = posixpath.dirname(posixpath.dirname(name))
            for target in re.findall(r'Target="([^"]+)"', deck.read(name).decode("utf-8")):
                if posixpath.normpath(posixpath.join(owner_dir, target)) == media:
                    hits.append(posixpath.basename(name)[:-5])
    return sorted(set(hits))


def rewrite(src: Path, dst: Path, swaps: dict[str, bytes]) -> None:
    renamed = {posixpath.basename(emf): posixpath.basename(emf)[:-4] + ".png" for emf in swaps}
    with zipfile.ZipFile(src) as old, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            if info.filename in swaps:
                new.writestr(info.filename[:-4] + ".png", swaps[info.filename], zipfile.ZIP_STORED)
                continue
            data = old.read(info.filename)
            if info.filename.endswith(".rels"):
                text = data.decode("utf-8")
                for emf, png in renamed.items():
                    text = re.sub(r'(Target="[^"]*/)' + re.escape(emf) + '"', r"\g<1>" + png + '"', text)
                data = text.encode("utf-8")
            elif info.filename == "[Content_Types].xml":
                text = data.decode("utf-8")
                if not re.search(r'<Default\b[^>]*Extension="png"', text, re.I):
                    text = text.replace("</Types>", '<Default Extension="png" ContentType="image/png"/></Types>')
                data = text.encode("utf-8")
            new.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decks", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="rewrite the decks in place")
    args = parser.parse_args()
    status = 0
    for deck_path in args.decks:
        with zipfile.ZipFile(deck_path) as deck:
            swaps = plan(deck)
            where = {emf: slides_using(deck, emf) for emf in swaps}
        if not swaps:
            print(f"{deck_path.name}: nothing to fix")
            continue
        for emf, users in where.items():
            print(f"{deck_path.name}: {emf} -> .png  (used by {', '.join(users)})")
        if not args.apply:
            continue
        lock = deck_path.with_name("~$" + deck_path.name)
        if lock.exists():
            print(f"{deck_path.name}: SKIPPED, open in PowerPoint ({lock.name}); close it and re-run")
            status = 1
            continue
        _BACKUPS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deck_path, _BACKUPS / f"{deck_path.stem}.{time.strftime('%Y%m%d-%H%M%S')}{deck_path.suffix}")
        with tempfile.TemporaryDirectory() as tmp:
            fixed = Path(tmp) / deck_path.name
            rewrite(deck_path, fixed, swaps)
            with zipfile.ZipFile(fixed) as check:
                bad = check.testzip()
            if bad:
                print(f"{deck_path.name}: rewritten zip is corrupt at {bad}; deck left untouched")
                status = 1
                continue
            shutil.copyfile(fixed, deck_path)
        print(f"{deck_path.name}: fixed ({len(swaps)} picture(s)); backup in {_BACKUPS}")
    return status


if __name__ == "__main__":
    sys.exit(main())
