"""The session's "Seen slides" deck: every slide shown, as it was on screen, one page each.

  Victor Mac ─ slide_seen ─→ here ─→ seen_registry (what changed) ─→ toast on his Mac
                                 └─→ page from PowerPoint's own print ─→ seen.pdf
                                     ─→ Railway (as one more cached deck) ─→ participants

Victor Mac sends `slide_seen` when a slide has stayed 7 s with PowerPoint in front
(`qualified`) and again when he leaves it (`closed`), after saving the deck. Only while a
session is active: the deck belongs to that session (Victor, 2026-11-22).

The pages are not printed here: local_publish.py keeps every deck it printed as
`deck.pdf` + the fingerprint it was printed from, so a slide's page is that deck's page
if its version matches. When it does not (the slide was edited, or the deck was never
printed), the slide waits and its deck is printed — but never while PowerPoint is in
front, where the print's progress bar would cover his work, and never during a slide
show. Decks outside the slides catalog are printed too, into a local `deck.pdf` that is
not sent anywhere.

A print is asked for again every minute, but local_publish.py decides whether PowerPoint
really prints: a save whose print failed is printed again after ~5 and ~25 min, then no
more, and a deck with hidden slides (which PowerPoint's print leaves out) not at all. On
2026-11-23 three such decks were printed whole once a minute for a whole training day,
~340 prints, none of them kept.

Files: the registry in the session folder (`slides-seen.json`, next to
session-state.json); the pages and the assembled `seen.pdf` in the local cache, from
where they can always be rebuilt.
"""
from __future__ import annotations

import hashlib
import os
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError
from pypdf import PdfReader, PdfWriter

from daemon import log
from daemon.slides import seen_registry
from daemon.slides.local_publish import PrintOutcome
from daemon.slides.pptx_slides import fingerprint, slide_version
from daemon.slides.seen_registry import SeenRegistry, SeenSlide

REGISTRY_FILE = "slides-seen.json"
ZIP_FILENAME = "Slides seen.pdf"
_CACHE = Path.home() / "Library" / "Caches" / "training-assistant" / "slides-seen"
# The same save of a deck is asked for again only after this (deck closed, a slide show, a
# failed print — whose real retries local_publish.py spaces out much further).
_PRINT_RETRY_S = 60.0
_TICK_S = 10.0
_NAME = "slides"
_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def seen_slug(session_id: str) -> str:
    """The seen deck's slug on Railway: one more deck in its slides cache."""
    return "seen-slides-" + (_SLUG_UNSAFE.sub("-", session_id.lower()).strip("-") or "session")


def is_seen_slug(slug: str) -> bool:
    return slug.startswith("seen-slides-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SlideSeenEvent(BaseModel):
    """`slide_seen` from Victor Mac (addon_bridge_client.py)."""

    phase: str = "qualified"
    path: str
    deck: str = ""
    slide_id: int | str
    slide: int = 0
    at: str | None = None


class SeenDeckState(BaseModel):
    """What a participant needs to show the deck: in /state and in `slides_seen_updated`."""

    slug: str
    count: int
    updated_at: str | None = None


@dataclass
class Deps:
    """Everything outside this module, so the tests can stand it in."""

    active_session: Callable[[], str | None]
    registry_dir: Callable[[str], Path | None]  # the session folder
    cache_root: Path
    catalog_slug: Callable[[Path], str | None]  # the deck's slug in the slides catalog, if any
    page_of: Callable[[str, str, str], tuple[Path, int] | None]
    publish: Callable[[str, Path], PrintOutcome]  # print + send to Railway (catalog decks)
    print_locally: Callable[[str, Path], PrintOutcome]  # print only (other decks)
    powerpoint_frontmost: Callable[[], bool]
    upload: Callable[[str, Path], None]  # (slug, pdf) → Railway's slides cache
    broadcast: Callable[[SeenDeckState], None]  # → participants
    notify_trainer: Callable[[str, int, str], None]  # (deck, position, change) → Victor Mac


class SeenSlides:
    def __init__(self, deps: Deps):
        self.deps = deps
        self._lock = threading.RLock()
        self._registries: dict[str, SeenRegistry] = {}
        self._last_print: dict[str, tuple[float, float]] = {}  # deck key → (deck mtime, when)
        self._uploaded: dict[str, str | None] = {}  # session → updated_at Railway holds

    # ── files ──

    def _cache(self, session_id: str) -> Path:
        return self.deps.cache_root / _SLUG_UNSAFE.sub("-", session_id)

    def _registry_path(self, session_id: str) -> Path:
        folder = self.deps.registry_dir(session_id)
        return (folder if folder and folder.is_dir() else self._cache(session_id)) / REGISTRY_FILE

    def seen_pdf(self, session_id: str) -> Path:
        return self._cache(session_id) / "seen.pdf"

    def registry(self, session_id: str) -> SeenRegistry:
        with self._lock:
            if session_id not in self._registries:
                path = self._registry_path(session_id)
                try:
                    loaded = SeenRegistry.model_validate_json(path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    loaded = SeenRegistry(session_id=session_id)
                except (OSError, ValidationError, ValueError) as exc:
                    log.error(_NAME, f"Seen slides: unreadable {path}, starting empty: {exc}")
                    loaded = SeenRegistry(session_id=session_id)
                self._registries[session_id] = loaded
            return self._registries[session_id]

    def _save(self, registry: SeenRegistry) -> None:
        path = self._registry_path(registry.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(registry.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)

    # ── what participants see ──

    def state(self, session_id: str | None = None) -> SeenDeckState | None:
        session_id = session_id or self.deps.active_session()
        if not session_id:
            return None
        with self._lock:
            registry = self.registry(session_id)
            count = len(seen_registry.with_pages(registry)) if self.seen_pdf(session_id).exists() else 0
            return SeenDeckState(slug=seen_slug(session_id), count=count, updated_at=registry.updated_at if count else None)

    # ── a slide shown ──

    def on_slide_seen(self, event: SlideSeenEvent) -> None:
        session_id = self.deps.active_session()
        if not session_id:
            return  # no session, nothing to belong to
        source = Path(event.path)
        try:
            slides = dict(fingerprint(source).slides)
        except (OSError, KeyError, ValueError) as exc:  # not there, not a .pptx
            log.error(_NAME, f"Seen slides: cannot read {source.name}: {exc}")
            return
        slide_id = str(event.slide_id)
        digest = slides.get(slide_id)
        if digest is None:
            log.error(_NAME, f"Seen slides: slide id {slide_id} is not in {source.name}")
            return
        with self._lock:
            registry = self.registry(session_id)
            change = seen_registry.record(registry, str(source), event.deck or source.name, slide_id,
                                          slide_version(digest),
                                          event.at or _now())
            self._save(registry)
        if change:
            log.info(_NAME, f"📷 seen slide {change}: {source.name} #{event.slide} (id {slide_id})")
            self.deps.notify_trainer(event.deck or source.name, event.slide, change)
        self.resolve(session_id)

    # ── pages ──

    def _deck_key(self, deck_path: Path) -> tuple[str, bool]:
        slug = self.deps.catalog_slug(deck_path)
        if slug:
            return slug, True
        stem = _SLUG_UNSAFE.sub("-", deck_path.stem.lower()).strip("-")
        return f"local-{stem}-{hashlib.sha1(str(deck_path).encode()).hexdigest()[:6]}", False

    def _take_page(self, session_id: str, slide: SeenSlide, deck_pdf: Path, index: int, version: str) -> None:
        pages = self._cache(session_id) / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_page(PdfReader(str(deck_pdf)).pages[index])
        target = pages / seen_registry.page_file_name(version)
        with open(target.with_suffix(".tmp"), "wb") as out:
            writer.write(out)
        os.replace(target.with_suffix(".tmp"), target)
        slide.page = version
        slide.version = version

    def resolve(self, session_id: str | None = None) -> None:
        """Give every waiting slide its page, print the decks still missing some, and
        publish the deck when it changed."""
        session_id = session_id or self.deps.active_session()
        if not session_id:
            return
        dirty, to_print = self._take_pages(session_id)
        if self._print(to_print):
            dirty |= self._take_pages(session_id)[0]  # what the print just brought
        if dirty:
            self._assemble(session_id)
        self._upload_if_behind(session_id)

    def _take_pages(self, session_id: str) -> tuple[bool, dict[str, tuple[Path, bool]]]:
        """Pages for the waiting slides that a print already has; the decks to print for
        the others. True when the registry changed."""
        to_print: dict[str, tuple[Path, bool]] = {}
        with self._lock:
            registry = self.registry(session_id)
            dirty = False
            for slide in list(seen_registry.pending(registry)):
                source = Path(slide.deck_path)
                key, catalog = self._deck_key(source)
                hit = self.deps.page_of(key, slide.slide_id, slide.version)
                if hit:
                    self._take_page(session_id, slide, *hit, slide.version)
                    dirty = True
                    continue
                try:
                    current = dict(fingerprint(source).slides).get(slide.slide_id)
                except (OSError, KeyError, ValueError):
                    current = None
                current = slide_version(current) if current is not None else None
                if current is None:
                    # The deck or the slide is gone: the version shown can no longer be printed.
                    if slide.page is None:
                        registry.slides.remove(slide)
                    else:
                        slide.version = slide.page
                    log.info(_NAME, f"Seen slides: {source.name} id {slide.slide_id} is gone — kept what was printed")
                    dirty = True
                    continue
                if current != slide.version:
                    # Edited again after it was shown, before its page was printed: the
                    # shown version is lost. Keep the page there is, else take the newer one.
                    if slide.page is not None:
                        slide.version = slide.page
                        dirty = True
                        continue
                    hit = self.deps.page_of(key, slide.slide_id, current)
                    if hit:
                        self._take_page(session_id, slide, *hit, current)
                        dirty = True
                        continue
                to_print[key] = (source, catalog)
            if dirty:
                self._save(registry)
        return dirty, to_print

    def _print(self, decks: dict[str, tuple[Path, bool]]) -> bool:
        """True when a deck was printed."""
        printed = False
        for key, (source, catalog) in decks.items():
            try:
                mtime = source.stat().st_mtime
            except OSError:
                continue
            last = self._last_print.get(key)
            if last and last[0] == mtime and time.monotonic() - last[1] < _PRINT_RETRY_S:
                continue  # asked a moment ago and still no page: not yet
            # Never under his hands: the print shows a progress bar. Asked before every
            # deck — a whole deck takes ~20 s to print, and he may be back by the next one.
            # (local_publish asks once more when the print is really about to start.)
            if self.deps.powerpoint_frontmost():
                break
            # Noted before the call: whatever it raises, the next tick 10 s later must not
            # ask again.
            self._last_print[key] = (mtime, time.monotonic())
            try:
                outcome = (self.deps.publish if catalog else self.deps.print_locally)(key, source)
            except Exception as exc:  # noqa: BLE001 — the other decks still get their turn
                log.error(_NAME, f"Seen slides: printing {source.name} failed: {exc}")
                continue
            if outcome == "done":
                log.info(_NAME, f"Seen slides: printed {source.name} for slides shown since its last print")
                printed = True
        return printed

    def _assemble(self, session_id: str) -> None:
        with self._lock:
            registry = self.registry(session_id)
            pages = self._cache(session_id) / "pages"
            writer = PdfWriter()
            missing = False
            for slide in seen_registry.with_pages(registry):
                page = pages / seen_registry.page_file_name(slide.page or "")
                if not page.exists():  # the cache was emptied: print it again
                    slide.page = None
                    missing = True
                    continue
                writer.append(str(page))
            target = self.seen_pdf(session_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            if len(writer.pages):
                with open(target.with_suffix(".tmp"), "wb") as out:
                    writer.write(out)
                os.replace(target.with_suffix(".tmp"), target)
            else:
                target.unlink(missing_ok=True)
            registry.updated_at = _now()
            self._save(registry)
            if missing:
                log.info(_NAME, "Seen slides: some pages were missing from the cache — they wait for a print")

    def _upload_if_behind(self, session_id: str, force: bool = False) -> None:
        with self._lock:
            state = self.state(session_id)
            if state is None or (not force and self._uploaded.get(session_id) == state.updated_at):
                return
            pdf = self.seen_pdf(session_id)
        if state.count and pdf.exists():
            try:
                self.deps.upload(state.slug, pdf)
            except Exception as exc:  # noqa: BLE001 — tried again at the next tick
                log.error(_NAME, f"Seen slides: upload failed, retrying: {exc}")
                return
            log.info(_NAME, f"↑ seen slides: {state.count} pages, {pdf.stat().st_size // 1024} KB")
        self._uploaded[session_id] = state.updated_at
        self.deps.broadcast(state)

    def reupload(self) -> None:
        """Railway's slides cache is lost on its restarts: send the deck again."""
        session_id = self.deps.active_session()
        if session_id:
            self._upload_if_behind(session_id, force=True)

    def clear(self) -> None:
        """The host wiped the shown slides: the seen deck starts again too."""
        session_id = self.deps.active_session()
        if not session_id:
            return
        with self._lock:
            self._registries[session_id] = SeenRegistry(session_id=session_id, updated_at=_now())
            self._save(self._registries[session_id])
            self.seen_pdf(session_id).unlink(missing_ok=True)
        self._upload_if_behind(session_id)


# ── The daemon's instance: a worker thread fed by the addons bridge ──

_service: SeenSlides | None = None
_queue: queue.Queue = queue.Queue()
_thread: threading.Thread | None = None


def _registry_dir(session_id: str) -> Path | None:
    from daemon.session.state import (
        get_active_session_id,
        get_active_session_name,
        get_sessions_root,
    )

    root, name = get_sessions_root(), get_active_session_name()
    if root and name and get_active_session_id() == session_id:
        return root / name
    return None


def _upload(slug: str, pdf: Path) -> None:
    from daemon.slides.local_publish import _post

    _post(f"/api/slides/deck/{slug}", {}, pdf)


def _broadcast(state: SeenDeckState) -> None:
    from daemon.ws_messages import SlidesSeenUpdatedMsg
    from daemon.ws_publish import broadcast

    broadcast(SlidesSeenUpdatedMsg(**state.model_dump()))


def _notify_trainer(deck: str, slide: int, change: str) -> None:
    from daemon import addon_bridge_client

    addon_bridge_client.send_slide_seen_captured(deck, slide, change)


def _publish_catalog_deck(slug: str, source: Path) -> PrintOutcome:
    from daemon.slides import local_publish
    from daemon.slides.router import _mark_cache_status

    outcome = local_publish.attempt(slug, source, upload=True, in_front_ok=False)
    if outcome == "done":
        _mark_cache_status(slug, "cached")
    return outcome


def service() -> SeenSlides:
    global _service
    if _service is None:
        from daemon.session.state import get_active_session_id
        from daemon.slides import local_publish, save_origin

        _service = SeenSlides(Deps(
            active_session=get_active_session_id,
            registry_dir=_registry_dir,
            cache_root=_CACHE,
            catalog_slug=lambda path: _catalog_slug(path),
            page_of=local_publish.page_of,
            publish=_publish_catalog_deck,
            print_locally=lambda key, source: local_publish.attempt(key, source, upload=False, in_front_ok=False),
            powerpoint_frontmost=save_origin.powerpoint_frontmost,
            upload=_upload,
            broadcast=_broadcast,
            notify_trainer=_notify_trainer,
        ))
    return _service


_catalog_slug: Callable[[Path], str | None] = lambda path: None  # noqa: E731 — set by SlidesRunner


def set_catalog_resolver(resolver: Callable[[Path], str | None]) -> None:
    global _catalog_slug
    _catalog_slug = resolver


def _run() -> None:
    while True:
        try:
            item = _queue.get(timeout=_TICK_S)
        except queue.Empty:
            item = None
        try:
            if isinstance(item, SlideSeenEvent):
                service().on_slide_seen(item)
            else:
                service().resolve()
        except Exception as exc:  # noqa: BLE001 — the worker must outlive any one slide
            log.error(_NAME, f"Seen slides: {exc}")


def _ensure_worker() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_run, name="slides-seen", daemon=True)
        _thread.start()


def submit(data: dict) -> None:
    """A `slide_seen` from Victor Mac (called on the addons bridge thread)."""
    try:
        event = SlideSeenEvent.model_validate(data)
    except ValidationError as exc:
        log.error(_NAME, f"Seen slides: bad slide_seen {data}: {exc}")
        return
    _ensure_worker()
    _queue.put(event)


def wake() -> None:
    """A deck was just printed: waiting slides may have their page now."""
    if _thread is not None:
        _queue.put(None)


def start() -> None:
    _ensure_worker()
