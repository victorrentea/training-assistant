"""After a save, the slides that changed reach the participants as PowerPoint draws them.

The deck's PDF used to be Google Drive's conversion, fetched by Railway: nothing went
through the trainer's connection, but slides came out wrong (other emoji, so other line
breaks; Victor, 2026-11-18). Now, when the deck is open in PowerPoint:

  save → which slides changed (pptx_slides.py) → PowerPoint prints just those
  (pdf_printer.py) → cropped and compressed (pdf_pages.py) → uploaded, ~0.1 MB a slide
  → Railway puts them into the deck it holds.

When the save was Victor Mac's (its auto-save every 3 min, or its slides-seen save) and
PowerPoint is in front, the print waits until PowerPoint leaves the front: it shows a
progress bar (save_origin.py, loop.py; Victor, 2026-11-20). His own ⌘S prints at once.

The first time, and whenever slides were added, removed or moved, the whole deck is printed
and sent (~10 MB). Railway is told which deck the pages belong to (the SHA-256 of the one it
should have): after a Railway restart, or when it holds Google's version, it refuses and gets
the whole deck. Anything that goes wrong here returns False, and the caller falls back to
Google's PDF as before.

A deck with hidden slides is not printed at all: PowerPoint's print leaves them out, so the
pages no longer line up with the slides, and the print was thrown away after its progress
bar had been shown (2026-11-23: three such decks, each printed whole once a minute, all day).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfWriter

from daemon import log
from daemon.slides import pdf_pages, pdf_printer
from daemon.slides.pptx_slides import (
    DeckFingerprint,
    as_ranges,
    changed_positions,
    fingerprint,
    hidden_slides,
    slide_version,
)

_HOME = Path.home() / "Library" / "Caches" / "training-assistant" / "local-slides"
_UPLOAD_TIMEOUT_S = 120
# More changed slides than this share of the deck: one whole-deck print is simpler and
# resets what the swapped-in pages added (each carries its own copy of the fonts).
_MAX_CHANGED_SHARE = 0.25
_lock = threading.Lock()

# What became of one request to print a save of a deck:
#   done    — deck.pdf holds that save;
#   not_now — PowerPoint cannot print it at this moment (the deck is not open, a slide show
#             runs); nothing was printed, the same save can be asked for again;
#   failed  — this save does not print: asking again would show the print's progress bar
#             again for the same result. Only a new save of the deck is worth a new print.
PrintOutcome = Literal["done", "not_now", "failed"]


class PublishedDeck(BaseModel):
    """What was last sent for a deck."""

    fingerprint: DeckFingerprint
    box: tuple[float, float, float, float]  # where a slide sits on a printed page
    railway_sha256: str


def _folder(slug: str) -> Path:
    return _HOME / slug


def _load(slug: str) -> PublishedDeck | None:
    try:
        return PublishedDeck.model_validate_json((_folder(slug) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(slug: str, state: PublishedDeck) -> None:
    (_folder(slug) / "state.json").write_text(state.model_dump_json(), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(path: str, fields: dict[str, str], pdf: Path) -> dict:
    """POST a PDF to Railway as multipart; the JSON it answers. HTTPError on a refusal."""
    from daemon.slides.router import _railway_auth_header, _railway_base_url, _ssl_context

    boundary = f"----slides-{uuid.uuid4().hex}"
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ) + (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="pages.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{_railway_base_url()}{path}", data=body, method="POST",
        headers={"Authorization": _railway_auth_header(), "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=_UPLOAD_TIMEOUT_S, context=_ssl_context()) as response:
        return json.loads(response.read())


def _printed(deck_name: str, ranges: list[tuple[int, int]] | None, work: Path) -> Path:
    """What PowerPoint printed for those ranges, as one PDF."""
    files = pdf_printer.print_slides(deck_name, ranges)
    try:
        if len(files) == 1:
            return files[0].rename(work / "printed.pdf")
        writer = PdfWriter()
        for file in files:
            writer.append(str(file))
        with open(work / "printed.pdf", "wb") as target:
            writer.write(target)
        return work / "printed.pdf"
    finally:
        for file in files:
            file.unlink(missing_ok=True)


def _send_whole_deck(slug: str, deck: Path) -> str:
    answer = _post(f"/api/slides/deck/{slug}", {}, deck)
    log.info("slides", f"↑ whole deck as PowerPoint prints it: slug={slug}, {deck.stat().st_size / 1e6:.1f} MB")
    return str(answer["sha256"])


def publish(slug: str, source: Path) -> bool:
    """True once Railway holds the saved deck as PowerPoint prints it."""
    return attempt(slug, source, upload=True) == "done"


def print_locally(key: str, source: Path) -> bool:
    """The same print into `deck.pdf` under `key`, without sending it anywhere: for the
    seen slides of a deck that is not in the slides catalog (seen_slides.py)."""
    return attempt(key, source, upload=False) == "done"


def page_of(key: str, slide_id: str, version: str) -> tuple[Path, int] | None:
    """The printed deck and the 0-based page holding this version of the slide
    (pptx_slides.slide_version), if the last print has it."""
    state = _load(key)
    deck = _folder(key) / "deck.pdf"
    if state is None or not deck.exists():
        return None
    for index, (printed_id, printed_digest) in enumerate(state.fingerprint.slides):
        if printed_id == slide_id:
            return (deck, index) if slide_version(printed_digest) == version else None
    return None


def attempt(slug: str, source: Path, upload: bool) -> PrintOutcome:
    """`publish` (upload) or `print_locally`, saying why when it did not happen."""
    if not pdf_printer.supported():
        return "failed"
    try:
        with _lock:
            outcome = _publish(slug, source, upload)
    except Exception as exc:  # noqa: BLE001 — whatever fails, Google's PDF is still there
        log.error("slides", f"Local print failed for slug={slug}, falling back to Google Drive: {exc}")
        return "failed"
    if outcome == "done":
        from daemon.slides import seen_slides  # pages of slides shown meanwhile may be here now
        seen_slides.wake()
    return outcome


def _publish(slug: str, source: Path, upload: bool = True) -> PrintOutcome:
    hidden = hidden_slides(source)
    if hidden:
        log.info("slides", f"No local print for slug={slug}: {len(hidden)} hidden slides, which PowerPoint's print leaves out")
        return "failed"
    decks, slide_show = pdf_printer.open_decks()
    if source.name not in decks or slide_show:
        return "not_now"
    try:
        return "done" if _print_and_send(slug, source, upload) else "failed"
    finally:
        # Only the deck and its state are kept between saves.
        for leftover in ("printed.pdf", "cropped.pdf", "pages.pdf", "deck.new.pdf"):
            (_folder(slug) / leftover).unlink(missing_ok=True)


def _print_and_send(slug: str, source: Path, upload: bool = True) -> bool:

    folder = _folder(slug)
    folder.mkdir(parents=True, exist_ok=True)
    deck = folder / "deck.pdf"
    state = _load(slug) if deck.exists() else None
    after = fingerprint(source)
    changed = changed_positions(state.fingerprint if state else None, after)

    if state and changed == []:
        return True  # a save that changed no slide (speaker notes, a re-save)

    if state and changed and len(changed) <= max(3, len(after.slides) * _MAX_CHANGED_SHARE):
        printed = _printed(source.name, as_ranges(changed), folder)
        cropped, pages = folder / "cropped.pdf", folder / "pages.pdf"
        count = pdf_pages.crop(printed, state.box, cropped)
        if count != len(changed):
            raise RuntimeError(f"PowerPoint printed {count} pages for slides {changed}")
        pdf_pages.compress(cropped, pages, count)
        merged = folder / "deck.new.pdf"
        pdf_pages.replace_pages(deck, pages, changed, merged)
        os.replace(merged, deck)
        if not upload:
            _save(slug, PublishedDeck(fingerprint=after, box=state.box, railway_sha256=state.railway_sha256))
            return True
        try:
            answer = _post(
                f"/api/slides/pages/{slug}",
                {"base_sha256": state.railway_sha256, "positions": json.dumps(changed)},
                pages,
            )
            sha = str(answer["sha256"])
            log.info("slides", f"↑ slides {changed} as PowerPoint prints them: slug={slug}, {pages.stat().st_size // 1024} KB")
        except urllib.error.HTTPError as refused:
            if refused.code != 409:
                raise
            # Railway restarted, or holds Google's version: it gets the whole deck.
            sha = _send_whole_deck(slug, deck)
        _save(slug, PublishedDeck(fingerprint=after, box=state.box, railway_sha256=sha))
        return True

    printed = _printed(source.name, None, folder)
    box = pdf_pages.slide_box(printed)
    if not pdf_pages.matches_aspect(box, after.aspect):
        raise RuntimeError(f"The printed slides are at {box}, not the deck's {after.aspect:.3f} shape")
    cropped = folder / "cropped.pdf"
    count = pdf_pages.crop(printed, box, cropped)
    if count != len(after.slides):
        raise RuntimeError(f"PowerPoint printed {count} pages for a {len(after.slides)}-slide deck (hidden slides?)")
    fresh = folder / "deck.new.pdf"
    pdf_pages.compress(cropped, fresh, count)
    os.replace(fresh, deck)
    sha = _send_whole_deck(slug, deck) if upload else ""
    _save(slug, PublishedDeck(fingerprint=after, box=box, railway_sha256=sha))
    return True
