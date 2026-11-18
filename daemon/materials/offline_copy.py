"""Where the open-from-disk copy of the participant site (offline_site.py) comes from
and where it goes.

The snapshot is taken from this daemon's own participant API over loopback, the same way
Railway's requests reach it (daemon/proxy_handler.py), so the copy shows exactly what a
participant's page would have been given.

`interact.zip` in the session folder is for whoever opens the Google Drive folder later.
The folder is synced to Drive, so it is rewritten only once the content has stopped
changing for a while (a break, the end of the day), and only when it really differs: a
6 MB upload on every edit of the notes would compete with the screen share.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from daemon import log
from daemon.config import DAEMON_HOST_PORT
from daemon.materials.offline_site import (
    DRIVE_ZIP,
    OfflineDeck,
    build_site,
    capture_snapshot,
    fingerprint,
    site_zip,
    wiki_site_zip_of,
)

CHECK_INTERVAL_S = 60.0
SETTLE_S = 600.0
_TIMEOUT_S = 5.0


def _local_fetch(path: str) -> dict | None:
    """One answer of the daemon's participant API, or None when it has none (no agenda)."""
    url = f"http://127.0.0.1:{DAEMON_HOST_PORT}/api/participant/{path}"
    # trust_env=False: a loopback call must never go through a proxy from the environment.
    with httpx.Client(trust_env=False, timeout=_TIMEOUT_S) as client:
        response = client.get(url)
    if response.status_code != 200:
        return None
    answer = response.json()
    return answer if isinstance(answer, dict) else None


def current_site(
    decks: list[OfflineDeck] | None = None, fetch: Callable[[str], dict | None] = _local_fetch
) -> dict[str, bytes] | None:
    """The copy as of now, or None when there is no session to copy."""
    from daemon.wiki.publisher import published_site

    api = capture_snapshot(fetch)
    state = api.get("state")
    if not state:
        return None
    return build_site(
        api,
        session_name=str(state.get("session_name") or ""),
        decks=decks,
        wiki_site_zip=wiki_site_zip_of(published_site()),
    )


def write_drive_zip(session_folder: Path, files: dict[str, bytes]) -> bool:
    """Put the copy in the session folder as interact.zip. False when the one already
    there holds the same content (its fingerprint is kept as the zip's comment)."""
    digest = fingerprint(files).encode("ascii")
    target = session_folder / DRIVE_ZIP
    try:
        with zipfile.ZipFile(target) as existing:
            if existing.comment == digest:
                return False
    except (OSError, zipfile.BadZipFile):
        pass
    partial = session_folder / f".{DRIVE_ZIP}.part"
    partial.write_bytes(site_zip(files, comment=digest))
    partial.replace(target)
    return True


class OfflineCopyPublisher:
    """Polled from the daemon main loop; keeps the session folder's interact.zip current."""

    def __init__(
        self,
        site: Callable[[], dict[str, bytes] | None] = current_site,
        state: Callable[[], dict | None] = lambda: _local_fetch("state"),
        clock: Callable[[], float] = time.time,
    ):
        self._site = site
        self._state = state
        self._clock = clock
        self._last_poll = float("-inf")
        self._busy = False
        self._session_id: str | None = None
        self._seen: str | None = None      # what the session looked like at the last check
        self._seen_at = 0.0                # since when it has looked like that
        self._written: str | None = None   # what it looked like when the zip was last written

    def tick(self, session_id: str | None, session_folder: Path | None) -> None:
        now = self._clock()
        if now - self._last_poll < CHECK_INTERVAL_S or self._busy:
            return
        self._last_poll = now
        if session_id != self._session_id:
            self._session_id = session_id
            self._seen = self._written = None
        if not session_id or session_folder is None:
            return
        self._busy = True
        threading.Thread(
            target=self._check, args=(session_folder, now), name="offline-copy", daemon=True
        ).start()

    def _check(self, session_folder: Path, now: float) -> None:
        try:
            self.check(session_folder, now)
        except Exception as exc:  # noqa: BLE001 — a failed copy must never kill the poller
            log.error("materials", f"Offline copy failed: {exc}")
        finally:
            self._busy = False

    def check(self, session_folder: Path, now: float) -> None:
        state = self._state()
        if not state:
            return
        looks = hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()
        if looks != self._seen:
            self._seen, self._seen_at = looks, now
            return
        if looks == self._written or now - self._seen_at < SETTLE_S:
            return
        files = self._site()
        if files is None:
            return
        self._written = looks
        if write_drive_zip(session_folder, files):
            size = (session_folder / DRIVE_ZIP).stat().st_size
            log.info("materials", f"offline copy written: {DRIVE_ZIP} ({size // 1024} KB)")
