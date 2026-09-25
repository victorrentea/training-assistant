"""Keep the participants' Wiki in step with the session's wiki/ folder.

Polled from the daemon main loop. Cheap on purpose: a stat per page every few
seconds, and a (niced, background) Quartz build only once the vault has changed
AND the summarizer has stopped writing to it for a while. Railway then serves the
built pages as static files, so browsing the wiki never touches this machine.
"""
from __future__ import annotations

import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from daemon import log
from daemon.materials.upload import build_multipart, post_multipart
from daemon.wiki.builder import build_site, find_wiki_dir, fingerprint, zip_site

POLL_INTERVAL_S = 5.0
# The summarizer writes a vault in a burst of files; build once the burst is over.
SETTLE_S = 20.0
# A build that failed is not retried for the same content until this passes.
RETRY_AFTER_FAILURE_S = 300.0

_UPLOAD_PATH = "/api/wiki/upload"

# (session_id, wiki folder, content fingerprint) — what a published site was built from.
_Key = tuple[str, str, tuple[int, int, int]]


def session_title(session_folder: Path) -> str:
    """'2026-09-25 AI@Rabo' → 'AI@Rabo': the date prefix is noise in a page title."""
    name = session_folder.name
    _, _, rest = name.partition(" ")
    return rest.strip() or name


def build_zip(wiki_dir: Path, title: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="wiki-site-") as tmp:
        site = Path(tmp) / "site"
        build_site(wiki_dir, title, site)
        return zip_site(site)


def uploader(config) -> Callable[[str, bytes], None]:
    def upload(session_id: str, payload: bytes) -> None:
        body, boundary = build_multipart(
            {"session_id": session_id}, (f"wiki-{session_id}.zip", payload)
        )
        post_multipart(f"{config.server_url}{_UPLOAD_PATH}", body, boundary, config)

    return upload


class WikiPublisher:
    def __init__(
        self,
        upload: Callable[[str, bytes], None],
        on_change: Callable[[str | None], None],
        build: Callable[[Path, str], bytes] = build_zip,
        clock: Callable[[], float] = time.time,
    ):
        """on_change(updated_at) is told whenever the published state flips or refreshes."""
        self._build = build
        self._upload = upload
        self._on_change = on_change
        self._clock = clock
        self._lock = threading.Lock()
        self._last_poll = float("-inf")
        self._session_id: str | None = None
        self._published: _Key | None = None
        self._payload: bytes | None = None  # last published site, re-sent after a Railway restart
        self._resend = False
        self._failed: _Key | None = None
        self._failed_at = 0.0
        self._busy = False
        self.updated_at: str | None = None

    def invalidate(self) -> None:
        """Railway (re)connected and may have lost its copy: re-send the last site.

        Re-sends the cached zip rather than rebuilding, so a flaky connection never
        costs a Quartz build.
        """
        with self._lock:
            self._resend = self._payload is not None

    def tick(self, session_id: str | None, session_folder: Path | None) -> None:
        now = self._clock()
        if now - self._last_poll < POLL_INTERVAL_S:
            return
        self._last_poll = now

        wiki_dir = find_wiki_dir(session_folder) if session_id else None
        fp = fingerprint(wiki_dir) if wiki_dir else None

        with self._lock:
            if session_id != self._session_id:
                # A new session starts with no wiki until its own vault is built.
                self._session_id = session_id
                self._published = self._payload = self._failed = None
                self._resend = False
                self._set_updated_at(None)
            if self._busy:
                return
            if fp is None:
                self._set_updated_at(None)
                return
            key: _Key = (session_id, str(wiki_dir), fp)
            if key == self._published:
                if not self._resend:
                    return
                self._resend = False
                self._busy = True
                job, args = self._resend_cached, (session_id, self._payload)
            else:
                if key == self._failed and now - self._failed_at < RETRY_AFTER_FAILURE_S:
                    return
                if now - fp[1] / 1e9 < SETTLE_S:
                    return  # still being written
                self._busy = True
                job, args = self._build_and_publish, (key, wiki_dir, session_title(session_folder))

        threading.Thread(target=job, args=args, name="wiki-publish", daemon=True).start()

    def _build_and_publish(self, key: _Key, wiki_dir: Path, title: str) -> None:
        session_id = key[0]
        started = time.monotonic()
        try:
            payload = self._build(wiki_dir, title)
            self._upload(session_id, payload)
        except Exception as exc:  # noqa: BLE001 — any failure must not kill the poller
            log.error("wiki", f"Wiki publish failed: {exc}")
            with self._lock:
                self._busy = False
                self._failed, self._failed_at = key, self._clock()
            return
        log.info(
            "wiki",
            f"↑ published wiki: {key[2][0]} pages, {len(payload) // 1024} KB, "
            f"{time.monotonic() - started:.1f}s",
        )
        with self._lock:
            self._busy = False
            if self._session_id != session_id:
                return  # the session changed while building; this site is not for it
            self._published, self._payload = key, payload
            self._set_updated_at(datetime.now(timezone.utc).isoformat())

    def _resend_cached(self, session_id: str, payload: bytes) -> None:
        try:
            self._upload(session_id, payload)
            log.info("wiki", "↑ re-sent wiki after Railway reconnect")
        except Exception as exc:  # noqa: BLE001
            log.error("wiki", f"Wiki re-send failed: {exc}")
            with self._lock:
                self._resend = True
        finally:
            with self._lock:
                self._busy = False

    def _set_updated_at(self, value: str | None) -> None:
        if value == self.updated_at:
            return
        self.updated_at = value
        self._on_change(value)


_installed: WikiPublisher | None = None


def install(publisher: WikiPublisher) -> None:
    global _installed
    _installed = publisher


def wiki_updated_at() -> str | None:
    """What participants get in their state snapshot: None hides the Wiki entry."""
    return _installed.updated_at if _installed else None
