"""
PPTX-to-PDF conversion via Google Drive pull.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path

from daemon import log
from daemon.http import session_api_url, get_active_session_id
from daemon.misc.state import misc_state
from daemon.slides.daemon import SlidesDaemonConfig, _post_json, _ssl_context
from daemon.slides.drive_sync import _beep_local, _download_pdf_from_url, _is_google_drive_running

# ---------------------------------------------------------------------------
# Fingerprint probe helpers (ported from railway/features/slides/cache.py)
# ---------------------------------------------------------------------------

_FINGERPRINT_TIMEOUT_S = 60
_FINGERPRINT_INTERVAL_S = 3.0

# Per-slug baseline fingerprints tracked by the daemon
_fingerprints: dict[str, str] = {}


def _probe_fingerprint_sync(url: str) -> str:
    """
    Probe the remote URL for a fingerprint.
    HEAD first → ETag/Last-Modified/Content-Length → "hdr:{etag}|{lm}|{cl}".
    If HEAD 405 or no useful headers → GET + SHA256 → "body:{hash}".
    Raises on other HTTP errors.
    """
    ctx = _ssl_context()
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            etag = resp.headers.get("ETag", "")
            lm = resp.headers.get("Last-Modified", "")
            cl = resp.headers.get("Content-Length", "")
            if etag or lm or cl:
                return f"hdr:{etag}|{lm}|{cl}"
            # HEAD succeeded but no useful headers — fall through to GET
    except urllib.error.HTTPError as e:
        if e.code != 405:
            raise

    # Fallback: GET + SHA256
    req_get = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req_get, context=ctx, timeout=60) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    return f"body:{digest}"


async def _probe_fingerprint(url: str) -> str:
    """Async wrapper: run _probe_fingerprint_sync in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _probe_fingerprint_sync, url)


# ---------------------------------------------------------------------------
# Fingerprint poll loop (marks slug stale when GDrive PDF changes)
# ---------------------------------------------------------------------------

async def poll_fingerprint_until_changed(slug: str, url: str, baseline_fingerprint: str) -> None:
    """
    Poll GDrive fingerprint every 3s for up to 60s.
    If fingerprint changes: marks slug as stale in misc_state.slides_cache_status.
    If timeout: logs silently and returns.
    """
    _fingerprints[slug] = baseline_fingerprint
    deadline = time.monotonic() + _FINGERPRINT_TIMEOUT_S
    log.info("slides", f"fingerprint poll started for slug={slug}, baseline={baseline_fingerprint[:30]}...")

    while time.monotonic() < deadline:
        await asyncio.sleep(_FINGERPRINT_INTERVAL_S)
        try:
            new_fp = await _probe_fingerprint(url)
        except Exception as exc:
            log.error("slides", f"fingerprint probe error for slug={slug}: {exc}")
            continue

        if new_fp != _fingerprints[slug]:
            log.info("slides", f"fingerprint changed for slug={slug}: {_fingerprints[slug][:20]}... -> {new_fp[:20]}... — marking stale")
            _fingerprints[slug] = new_fp
            entry = misc_state.slides_cache_status.get(slug) or {}
            misc_state.slides_cache_status[slug] = {**entry, "status": "stale"}
            return

    log.info("slides", f"fingerprint poll timeout for slug={slug} after {_FINGERPRINT_TIMEOUT_S:.0f}s — no change detected")


def _push_error_status(config: SlidesDaemonConfig, message: str) -> None:
    if not config.sync_backend:
        return
    payload = {
        "status": "error",
        "message": message,
        "slides": [],
    }
    try:
        sid = get_active_session_id(config.server_url)
        _post_json(
            session_api_url(config.server_url, sid, "/quiz-status"),
            payload,
            config.host_username,
            config.host_password,
        )
    except Exception:
        pass


def convert_with_google_drive_pull(
    pptx_path: Path,
    output_pdf: Path,
    config: SlidesDaemonConfig,
    state_entry: dict,
    drive_export_url: str,
    drive_probe_url: str,
) -> Path:
    if not drive_export_url:
        raise RuntimeError(f"drive_url_error: Missing drive_export_url for {pptx_path.name}")

    previous_fingerprint = str(state_entry.get("last_drive_fingerprint") or "").strip()
    _ = drive_probe_url  # Reserved for future diagnostics.
    deadline = time.time() + max(10.0, float(config.drive_sync_timeout_seconds))
    poll_interval = max(1.0, float(config.drive_poll_seconds))
    attempts = 0
    last_error: str | None = None

    while True:
        attempts += 1
        try:
            pdf_path = _download_pdf_from_url(drive_export_url, output_pdf)
            payload = pdf_path.read_bytes()
            fingerprint = f"pdf:{hashlib.sha256(payload).hexdigest()}"
            state_entry["last_drive_probe_at"] = time.time()
            if previous_fingerprint and fingerprint == previous_fingerprint:
                last_error = (
                    f"drive_not_synced_yet: {pptx_path.name} changed locally but Drive PDF fingerprint "
                    f"is still unchanged (attempt {attempts})."
                )
                state_entry["last_drive_error"] = last_error
                try:
                    pdf_path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                state_entry["last_drive_fingerprint"] = fingerprint
                state_entry["last_drive_ready_at"] = time.time()
                state_entry["last_drive_error"] = None
                state_entry["out_of_sync"] = False
                state_entry["out_of_sync_message"] = None
                log.info("slides", f"⬇️ Google Drive PDF downloaded: {pptx_path.name} (attempt {attempts})")
                return pdf_path
        except Exception as exc:
            last_error = str(exc)
            state_entry["last_drive_error"] = last_error

        if time.time() >= deadline:
            break
        time.sleep(poll_interval)

    drive_running = _is_google_drive_running()
    health_hint = "" if drive_running else " Google Drive app not running."
    message = (
        f"drive_sync_timeout: {pptx_path.name} not updated in Drive within "
        f"{int(config.drive_sync_timeout_seconds)}s after local change.{health_hint}"
    )
    if last_error:
        message += f" Last error: {last_error}"
    state_entry["out_of_sync"] = True
    state_entry["out_of_sync_message"] = message
    state_entry["last_drive_error"] = message
    _push_error_status(config, message)
    if not drive_running:
        _beep_local()
    raise RuntimeError(message)


def convert_pptx_to_pdf(
    pptx_path: Path,
    config: SlidesDaemonConfig,
    slug: str,
    state_entry: dict,
    metadata: dict | None = None,
) -> Path:
    work_pdf = config.work_dir / f"{slug}.pdf"
    metadata = metadata or {}
    drive_export_url = str(metadata.get("drive_export_url") or "").strip()
    drive_probe_url = str(metadata.get("drive_probe_url") or drive_export_url).strip()
    return convert_with_google_drive_pull(
        pptx_path=pptx_path,
        output_pdf=work_pdf,
        config=config,
        state_entry=state_entry,
        drive_export_url=drive_export_url,
        drive_probe_url=drive_probe_url,
    )
