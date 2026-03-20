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

import json
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
    post_status, _get_json, _post_json, DAEMON_POLL_INTERVAL, read_session_notes,
    load_transcription_files,
)
from daemon.summarizer import generate_summary, SUMMARY_INTERVAL_SECONDS

_LOCK_FILE = Path("/tmp/quiz_daemon.lock")
_HEARTBEAT_INTERVAL = 1.0  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 10.0  # seconds before heartbeat is considered stale
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


def _read_lock() -> tuple[int | None, float | None]:
    """Read PID and last heartbeat from lock file. Returns (None, None) if missing/corrupt."""
    if not _LOCK_FILE.exists():
        return None, None
    try:
        data = json.loads(_LOCK_FILE.read_text())
        return int(data["pid"]), float(data["heartbeat"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, None


def _write_lock() -> None:
    """Write current PID and heartbeat timestamp to lock file."""
    _LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "heartbeat": time.time()}))


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)  # signal 0 = check existence only
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _check_and_acquire_lock() -> None:
    """Check lock file and decide whether to start, kill previous, or abort."""
    pid, heartbeat = _read_lock()

    if pid is None:
        # No lock file or corrupt — safe to start
        return

    if pid == os.getpid():
        return

    alive = _is_process_alive(pid)
    heartbeat_age = time.time() - heartbeat if heartbeat else float("inf")

    if alive and heartbeat_age <= _HEARTBEAT_STALE_THRESHOLD:
        # Previous instance is healthy — abort
        print(f"[daemon] Another instance is already running (PID {pid}, "
              f"heartbeat {heartbeat_age:.1f}s ago). Exiting.")
        sys.exit(0)

    if alive and heartbeat_age > _HEARTBEAT_STALE_THRESHOLD:
        # Process exists but heartbeat is stale — something is wrong
        print(f"⚠️  [daemon] Previous instance (PID {pid}) is alive but heartbeat "
              f"is stale ({heartbeat_age:.0f}s ago). Killing it.")
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ProcessLookupError, PermissionError):
            pass

    if not alive:
        # Process is dead — stale lock file from a crash
        print(f"[daemon] Previous instance (PID {pid}) is dead (crashed?). Cleaning up lock file.")

    _LOCK_FILE.unlink(missing_ok=True)


def run() -> None:
    _check_and_acquire_lock()
    _write_lock()

    def _cleanup(*_):
        _LOCK_FILE.unlink(missing_ok=True)
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
    last_heartbeat_at = 0.0
    last_session_check_at = 0.0
    last_transcript_stats_at = 0.0
    # Summary state
    summary_points: list[dict] = []
    last_summary_at = 0.0  # monotonic time of last summary run

    while True:
        try:
            # ── Heartbeat: update lock file so other instances know we're alive ──
            now = time.monotonic()
            if now - last_heartbeat_at >= _HEARTBEAT_INTERVAL:
                _write_lock()
                last_heartbeat_at = now

            timestamp_appender.tick()

            # ── Re-detect session folder on date change or if notes not yet found (every 5s) ──
            today = date.today()
            notes_missing = config.session_notes is None
            date_changed = today != last_detected_date
            session_recheck_due = notes_missing and (now - last_session_check_at >= 5.0)
            if date_changed or session_recheck_due:
                last_session_check_at = now
                sf, sn = find_session_folder(today)
                changed = (sf != config.session_folder or sn != config.session_notes)
                if changed or date_changed:
                    config = dc_replace(config, session_folder=sf, session_notes=sn)
                    last_detected_date = today
                    if sf:
                        print(f"[session] Detected: {sf.name} / notes: {sn.name if sn else 'none'}")
                    else:
                        print("[session] No session folder for today", file=sys.stderr)
                    _session_status_pending = True
                else:
                    _session_status_pending = False
            else:
                _session_status_pending = False

            sf_name = config.session_folder.name if config.session_folder else None
            sn_name = config.session_notes.name if config.session_notes else None

            # ── Check for new quiz generation request ──
            data = _get_json(
                f"{config.server_url}/api/quiz-request",
                config.host_username, config.host_password,
            )
            if server_disconnected:
                print("[daemon] Reconnected to server.")
                server_disconnected = False
                _session_status_pending = True

            # ── Push session info when changed, on reconnect, or if server lost it ──
            server_has_session = data.get("session_folder") is not None
            server_has_notes = data.get("has_notes_content", False)
            if _session_status_pending or (sf_name and not server_has_session):
                post_status("ready", "Agent ready.", config,
                            session_folder=sf_name, session_notes=sn_name)

            # Push notes content if server doesn't have it yet
            if config.session_notes and not server_has_notes:
                notes_text = read_session_notes(config)
                if notes_text:
                    _post_json(
                        f"{config.server_url}/api/notes",
                        {"content": notes_text},
                        config.host_username, config.host_password,
                    )
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

            # ── Push transcript stats every 10s ──
            if now - last_transcript_stats_at >= 10.0:
                last_transcript_stats_at = now
                try:
                    entries = load_transcription_files(config.folder)
                    timed = [(ts, txt) for ts, txt in entries if ts is not None]
                    if timed:
                        max_ts = max(ts for ts, _ in timed)
                        cutoff = max_ts - 30 * 60
                        recent = [(ts, txt) for ts, txt in timed if ts >= cutoff and txt.strip()]
                        line_count = len(recent)
                        # Convert max_ts (seconds from midnight) to today's ISO time
                        h, rem = divmod(int(max_ts), 3600)
                        m, s = divmod(rem, 60)
                        latest_time = f"{h:02d}:{m:02d}:{s:02d}"
                    else:
                        line_count = 0
                        latest_time = None
                    _post_json(
                        f"{config.server_url}/api/transcript-status",
                        {"line_count": line_count, "latest_ts": latest_time},
                        config.host_username, config.host_password,
                    )
                except SystemExit:
                    pass
                except Exception:
                    pass

            # ── Check for forced summary request ──
            force_summary = False
            try:
                force_data = _get_json(
                    f"{config.server_url}/api/summary/force",
                    config.host_username, config.host_password,
                )
                force_summary = force_data.get("requested", False)
            except Exception:
                pass

            # ── Periodic or forced summary generation ──
            now_mono = time.monotonic()
            if force_summary or now_mono - last_summary_at >= SUMMARY_INTERVAL_SECONDS:
                if force_summary:
                    print("[summarizer] Force-generating summary (host requested)")
                last_summary_at = now_mono
                try:
                    new_points = generate_summary(config, summary_points)
                    if new_points is not None:
                        summary_points = new_points
                        _post_json(
                            f"{config.server_url}/api/summary",
                            {"points": summary_points},
                            config.host_username, config.host_password,
                        )
                except Exception as e:
                    print(f"[summarizer] Error during summary generation: {e}", file=sys.stderr)

        except RuntimeError as e:
            if not server_disconnected:
                print(f"[daemon] Server unreachable: {e}", file=sys.stderr)
                server_disconnected = True
        except KeyboardInterrupt:
            _LOCK_FILE.unlink(missing_ok=True)
            print("\n[daemon] Stopped.")
            return
        except Exception as e:
            # Keep daemon alive for unexpected transient errors; loop retries.
            print(f"[daemon] Unexpected error (will retry): {e}", file=sys.stderr)
        time.sleep(DAEMON_POLL_INTERVAL)


if __name__ == "__main__":
    run()
