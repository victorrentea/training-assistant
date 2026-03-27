"""
PPTX-to-PDF conversion via Google Drive pull.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from daemon import log
from daemon.slides.daemon import SlidesDaemonConfig, _post_json
from daemon.slides.drive_sync import _beep_local, _download_pdf_from_url, _is_google_drive_running


def _push_error_status(config: SlidesDaemonConfig, message: str) -> None:
    if not config.sync_backend:
        return
    payload = {
        "status": "error",
        "message": message,
        "slides": [],
    }
    try:
        _post_json(
            f"{config.server_url}/api/quiz-status",
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
