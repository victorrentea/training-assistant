#!/usr/bin/env python3
"""
Quiz Daemon — runs in the background on the trainer's Mac.

Polls the workshop server for quiz generation requests triggered from the
host panel, then runs the full generate → post → open flow automatically.

Usage:
    python3 quiz_daemon.py

All configuration is read from secrets.env and environment variables:
    ANTHROPIC_API_KEY       Claude API key (required)
    WORKSHOP_SERVER_URL     e.g. https://interact.victorrentea.ro
    HOST_USERNAME / HOST_PASSWORD
    TRANSCRIPTION_FOLDER    path to transcription files
"""

import os
import signal
import sys
import time
from dataclasses import replace as dc_replace
from datetime import date
from pathlib import Path

from daemon.transcript_timestamps import (
    append_empty_line_then_timestamp,
    infer_template_from_first_line,
)
from quiz_core import (
    config_from_env, find_session_folder, auto_generate, auto_generate_topic, auto_refine,
    post_status, _get_json, DAEMON_POLL_INTERVAL,
)

_PID_FILE = Path("/tmp/quiz_daemon.pid")
_TIMESTAMP_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS", "3"))


class TranscriptTimestampAppender:
    """Append heartbeat timestamp lines to the latest transcript text file."""

    def __init__(self, folder: Path, interval_seconds: float = _TIMESTAMP_INTERVAL_SECONDS):
        self.folder = folder
        self.interval_seconds = interval_seconds
        self.enabled = False
        self._next_append_at = 0.0
        self._target_file: Path | None = None
        self._template = None
        self._startup_error_logged = False

    def _resolve_target_file(self) -> Path | None:
        if not self.folder.exists() or not self.folder.is_dir():
            return None
        txt_files = sorted(
            [f for f in self.folder.iterdir() if f.suffix.lower() == ".txt"],
            key=lambda f: f.stat().st_mtime,
        )
        return txt_files[-1] if txt_files else None

    def _log_startup_error_once(self, message: str) -> None:
        if self._startup_error_logged:
            return
        print(message, file=sys.stderr)
        self._startup_error_logged = True

    def start(self) -> None:
        if self.interval_seconds <= 0:
            self._log_startup_error_once(
                "[daemon] Transcript timestamp appender disabled: "
                "TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS must be > 0"
            )
            return

        self._target_file = self._resolve_target_file()
        if self._target_file is None:
            self._log_startup_error_once(
                f"[daemon] Transcript timestamp appender disabled: no .txt transcript found in {self.folder}"
            )
            return

        self._template = infer_template_from_first_line(self._target_file)
        self._next_append_at = time.monotonic()
        self.enabled = True
        print(
            "[daemon] Transcript timestamp appender enabled "
            f"({self.interval_seconds:.1f}s) on {self._target_file.name}"
        )

    def tick(self) -> None:
        if not self.enabled:
            return

        now = time.monotonic()
        if now < self._next_append_at:
            return

        try:
            append_empty_line_then_timestamp(self._target_file, self._template)
        except OSError as exc:
            self.enabled = False
            print(
                f"[daemon] Transcript timestamp appender stopped: {exc}",
                file=sys.stderr,
            )
            return

        self._next_append_at = now + self.interval_seconds


def _kill_previous() -> None:
    if not _PID_FILE.exists():
        return
    try:
        pid = int(_PID_FILE.read_text().strip())
        if pid == os.getpid():
            return
        os.kill(pid, signal.SIGTERM)
        print(f"[daemon] Killed previous instance (PID {pid})")
        time.sleep(0.5)
    except (ValueError, ProcessLookupError, PermissionError):
        pass  # stale or already gone
    _PID_FILE.unlink(missing_ok=True)


def run() -> None:
    _kill_previous()
    _PID_FILE.write_text(str(os.getpid()))

    def _cleanup(*_):
        _PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    config = config_from_env()

    # Detect today's session folder
    sf, sn = find_session_folder(date.today())
    config = dc_replace(config, session_folder=sf, session_notes=sn)
    if sf:
        print(f"[session] Session folder: {sf.name}")
        print(f"[session] Notes file: {sn.name if sn else 'NOT FOUND'}")
    else:
        print("[session] No session folder found for today", file=sys.stderr)

    # Start background material indexer
    materials_folder_str = os.environ.get("MATERIALS_FOLDER",
        str(Path(__file__).parent / "materials"))
    materials_folder = Path(materials_folder_str).expanduser()
    if materials_folder.exists():
        from daemon.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        print(f"[daemon] MATERIALS_FOLDER not found: {materials_folder} — indexer disabled", file=sys.stderr)

    print(f"[daemon] Started — polling {config.server_url} every {DAEMON_POLL_INTERVAL}s")
    print("[daemon] Press Ctrl+C to stop.\n")

    timestamp_appender = TranscriptTimestampAppender(config.folder)
    timestamp_appender.start()

    # Session state: the transcript text used to generate the current preview
    last_text: str | None = None
    last_quiz: dict | None = None
    server_disconnected = False
    last_detected_date: date | None = None

    while True:
        try:
            timestamp_appender.tick()

            # ── Re-detect session folder on date change ──
            today = date.today()
            if today != last_detected_date:
                sf, sn = find_session_folder(today)
                config = dc_replace(config, session_folder=sf, session_notes=sn)
                last_detected_date = today
                if sf:
                    print(f"[session] Detected: {sf.name} / notes: {sn.name if sn else 'none'}")
                else:
                    print("[session] No session folder for today", file=sys.stderr)
                # Push session status to server so host UI updates immediately
                _session_status_pending = True
            else:
                _session_status_pending = False

            sf_name = config.session_folder.name if config.session_folder else None
            sn_name = config.session_notes.name if config.session_notes else None

            # ── Push session info when detected or on reconnect ──
            if _session_status_pending:
                post_status("ready", "Agent ready.", config,
                            session_folder=sf_name, session_notes=sn_name)

            # ── Check for new quiz generation request ──
            data = _get_json(
                f"{config.server_url}/api/quiz-request",
                config.host_username, config.host_password,
            )
            if server_disconnected:
                print("[daemon] Reconnected to server.")
                server_disconnected = False
                post_status("ready", "Agent reconnected.", config,
                            session_folder=sf_name, session_notes=sn_name)
            req = data.get("request")
            if req:
                topic = req.get("topic")
                minutes = req.get("minutes")
                if topic:
                    print(f"\n[daemon] Topic request: '{topic}'")
                    result = auto_generate_topic(topic, config)
                else:
                    minutes = minutes or config.minutes
                    print(f"\n[daemon] Transcript request: last {minutes} min")
                    result = auto_generate(minutes, config)
                if result:
                    last_quiz, last_text = result
                else:
                    last_quiz, last_text = None, None

            # ── Check for refine request ──
            refine_data = _get_json(
                f"{config.server_url}/api/quiz-refine",
                config.host_username, config.host_password,
            )
            refine_req = refine_data.get("request")
            if refine_req:
                target = refine_req.get("target", "question")
                # Use server-side preview as current quiz (in case host re-opened page)
                current_quiz = refine_data.get("preview") or last_quiz
                if current_quiz and last_text:
                    print(f"\n[daemon] Refine request: target={target}")
                    updated = auto_refine(target, current_quiz, last_text, config)
                    if updated:
                        last_quiz = updated
                else:
                    post_status("error", "No conversation context — please generate a question first.", config)

        except RuntimeError as e:
            if not server_disconnected:
                print(f"[daemon] Server unreachable: {e}", file=sys.stderr)
                server_disconnected = True
        except KeyboardInterrupt:
            _PID_FILE.unlink(missing_ok=True)
            print("\n[daemon] Stopped.")
            return
        except Exception as e:
            # Keep daemon alive for unexpected transient errors; loop retries.
            print(f"[daemon] Unexpected error (will retry): {e}", file=sys.stderr)
        time.sleep(DAEMON_POLL_INTERVAL)


if __name__ == "__main__":
    run()
