"""Proactively verify Google can still export a deck to PDF, and drive the
macOS add-on's persistent "PDF export failing" alarm.

Why: when a source PPTX grows too large, Google Drive stops being able to
render it to PDF (the /export/pdf endpoint returns an HTML error, e.g. HTTP
512 "File could not open"). Participants — and the daemon's own Railway
download — then fail. This module lets the daemon notice on its own, right
after a slide changes, without anyone requesting the deck.

The probe is a cheap HEAD (no body) that follows redirects and treats a
final HTTP 200 + Content-Type application/pdf as healthy — the same signal
the public slides page uses (`fetch(url, {method:'HEAD'}).then(r => r.ok)`).

After a change, Google needs time to re-render the export, so a probe fired
immediately would false-alarm. We therefore wait a grace period, then retry
for a window before alarming, and auto-clear once a later probe succeeds.
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from daemon import log
from daemon.addon_bridge_client import send_pdf_export_alarm
from daemon.slides.daemon import _ssl_context

_NAME = "slides "

# Timing — tuned for "60s grace, retry ~5 min" (see AskUserQuestion decision).
# Module-level so tests can shrink them.
GRACE_S: float = 60.0
RETRY_INTERVAL_S: float = 60.0
MAX_RETRY_WINDOW_S: float = 300.0  # keep retrying this long before alarming
RECHECK_INTERVAL_S: float = 60.0   # while alarm is active, re-probe cadence
PROBE_TIMEOUT_S: float = 30.0      # a large export can be slow to render

# One in-flight probe per slug; a newer change cancels the older probe.
_probes: dict[str, threading.Event] = {}
_alarming: set[str] = set()
_lock = threading.Lock()


def probe_drive_export(url: str, timeout: float = PROBE_TIMEOUT_S) -> tuple[bool, str]:
    """HEAD the Drive export URL (following redirects). Return (healthy, detail).

    Healthy == final HTTP 200 with Content-Type application/pdf. A failed
    export raises HTTPError (e.g. 512) which we report as unhealthy.
    """
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            status = int(resp.status)
            ctype = resp.headers.get("Content-Type", "") or ""
            healthy = status == 200 and ctype.lower().startswith("application/pdf")
            return healthy, f"HTTP {status}, Content-Type {ctype or 'n/a'}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def schedule_probe(slug: str, deck_title: str, drive_export_url: str) -> None:
    """Start (or restart) the grace→retry→alarm probe for a changed deck.

    Best-effort and non-blocking: runs on a daemon thread. A new change for
    the same slug supersedes any in-flight probe.
    """
    if not drive_export_url:
        return
    with _lock:
        prev = _probes.get(slug)
        if prev is not None:
            prev.set()  # cancel the superseded probe
        cancel = threading.Event()
        _probes[slug] = cancel
    threading.Thread(
        target=_probe_worker,
        args=(slug, deck_title or slug, drive_export_url, cancel),
        daemon=True,
        name=f"export-probe-{slug}",
    ).start()


def _probe_worker(slug: str, deck_title: str, url: str, cancel: threading.Event) -> None:
    try:
        if cancel.wait(GRACE_S):
            return
        deadline = time.monotonic() + MAX_RETRY_WINDOW_S
        detail = ""
        while not cancel.is_set():
            healthy, detail = probe_drive_export(url)
            if healthy:
                _clear_alarm(slug, deck_title)
                return
            log.info(_NAME, f"⏳ PDF export not ready for slug={slug} ({detail})")
            if time.monotonic() >= deadline:
                break
            if cancel.wait(RETRY_INTERVAL_S):
                return

        # Window exhausted and still failing → raise the alarm, then keep
        # re-probing (slowly) so we can auto-clear the moment it recovers.
        _raise_alarm(slug, deck_title, detail)
        while not cancel.wait(RECHECK_INTERVAL_S):
            healthy, detail = probe_drive_export(url)
            if healthy:
                _clear_alarm(slug, deck_title)
                return
    finally:
        with _lock:
            # Only forget this probe if it's still the current one.
            if _probes.get(slug) is cancel:
                _probes.pop(slug, None)


def _raise_alarm(slug: str, deck_title: str, detail: str) -> None:
    with _lock:
        _alarming.add(slug)
    log.error(_NAME, f"🚨 PDF export FAILING for deck={deck_title!r} slug={slug} ({detail}) — alarming macOS")
    send_pdf_export_alarm(deck=deck_title, slug=slug, failing=True, detail=detail)


def _clear_alarm(slug: str, deck_title: str) -> None:
    with _lock:
        was_alarming = slug in _alarming
        _alarming.discard(slug)
    if was_alarming:
        log.info(_NAME, f"✅ PDF export recovered for deck={deck_title!r} slug={slug} — clearing macOS alarm")
        send_pdf_export_alarm(deck=deck_title, slug=slug, failing=False, detail="recovered")
