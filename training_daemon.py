#!/usr/bin/env python3
"""
Training Daemon — runs in the background on the trainer's Mac.

Polls the workshop server for quiz generation requests triggered from the
host panel, then runs the full generate → post → open flow automatically.

Usage:
    python3 training_daemon.py

All configuration is read from secrets.env and environment variables:
    ANTHROPIC_API_KEY       Claude API key (required)
    WORKSHOP_SERVER_URL     e.g. https://interact.victorrentea.ro
    HOST_USERNAME / HOST_PASSWORD
    TRANSCRIPTION_FOLDER    path to transcription files
"""

import json
import logging
import os
import re
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
from dataclasses import replace as dc_replace
from datetime import date, datetime
from pathlib import Path

from daemon.transcript_timestamps import (
    append_empty_line_then_timestamp,
    infer_template_from_first_line,
)
from quiz_core import (
    config_from_env, find_session_folder, auto_generate, auto_generate_topic, auto_refine,
    post_status, _get_json, _post_json, DAEMON_POLL_INTERVAL, DEFAULT_TRANSCRIPT_MINUTES,
    read_session_notes, load_transcription_files, extract_last_n_minutes, extract_all_text,
)
from daemon.debate_ai import run_debate_ai_cleanup
from daemon.llm_adapter import get_usage
from daemon.summarizer import generate_summary
from daemon.transcript_state import TranscriptStateManager

_LOCK_FILE = Path("/tmp/training_daemon.lock")
_HEARTBEAT_INTERVAL = 1.0  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 10.0  # seconds before heartbeat is considered stale
_TIMESTAMP_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS", "3"))
EXIT_CODE_UPDATE = 42  # signals start.sh to git pull and restart
_SUMMARY_CACHE_FILENAME = "summary_cache.json"


def _load_summary_cache(session_folder: Path | None) -> tuple[list[dict], list[dict]]:
    """Load cached summary points from session folder. Returns (locked, draft)."""
    if not session_folder:
        return [], []
    cache_file = session_folder / _SUMMARY_CACHE_FILENAME
    if not cache_file.exists():
        return [], []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        locked = data.get("locked", [])
        draft = data.get("draft", [])
        print(f"[summarizer] Loaded cached summary: {len(locked)} locked + {len(draft)} draft points")
        return locked, draft
    except Exception as e:
        print(f"[summarizer] Failed to load summary cache: {e}", file=sys.stderr)
        return [], []


def _save_summary_cache(session_folder: Path | None, locked: list[dict], draft: list[dict]) -> None:
    """Save summary points to session folder for persistence across restarts."""
    if not session_folder:
        return
    cache_file = session_folder / _SUMMARY_CACHE_FILENAME
    try:
        cache_file.write_text(json.dumps({"locked": locked, "draft": draft}, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[summarizer] Failed to save summary cache: {e}", file=sys.stderr)


_KEY_POINTS_FILENAME = "key_points.json"
_DAEMON_STATE_FILENAME = "daemon_state.json"


def _load_key_points(session_folder: Path) -> list[dict]:
    """Load key points from session folder. Supports old locked/draft format for migration."""
    cache_file = session_folder / _KEY_POINTS_FILENAME
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        # Support new format {"points": [...]} and old format {"locked": [...], "draft": [...]}
        points = data.get("points", data.get("locked", []) + data.get("draft", []))
        print(f"[session] Loaded {len(points)} key points from {session_folder.name}")
        return points
    except Exception as e:
        print(f"[session] Failed to load key points: {e}", file=sys.stderr)
        return []


def _save_key_points(session_folder: Path, points: list[dict]) -> None:
    """Save key points to session folder."""
    try:
        session_folder.mkdir(parents=True, exist_ok=True)
        (session_folder / _KEY_POINTS_FILENAME).write_text(
            json.dumps({"points": points}, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[session] Failed to save key points: {e}", file=sys.stderr)


def _load_daemon_state(sessions_root: Path) -> list[dict]:
    """Load session stack from daemon state file."""
    state_file = sessions_root / _DAEMON_STATE_FILENAME
    if not state_file.exists():
        return []
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data.get("stack", [])
    except Exception as e:
        print(f"[session] Failed to load daemon state: {e}", file=sys.stderr)
        return []


def _save_daemon_state(sessions_root: Path, stack: list[dict]) -> None:
    """Persist session stack to daemon state file."""
    try:
        sessions_root.mkdir(parents=True, exist_ok=True)
        (sessions_root / _DAEMON_STATE_FILENAME).write_text(
            json.dumps({"stack": stack}, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[session] Failed to save daemon state: {e}", file=sys.stderr)


def _find_notes_in_folder(folder: Path) -> Path | None:
    """Find the most recently modified .txt notes file in a session folder."""
    if not folder.exists():
        return None
    txt_files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    return txt_files[-1] if txt_files else None


def _sync_session_to_server(config, stack: list[dict], key_points: list[dict]) -> None:
    """Push session stack and key points to server."""
    _post_json(
        f"{config.server_url}/api/session/sync",
        {"stack": stack, "key_points": key_points},
        config.host_username, config.host_password,
    )


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
        _date_re = re.compile(r"^(\d{8})\s+(\d{4})\b")

        def _sort_key(f: Path):
            m = _date_re.match(f.name)
            return m.group(1) + m.group(2) if m else ""

        txt_files = sorted(
            [f for f in self.folder.iterdir() if f.suffix.lower() == ".txt"],
            key=_sort_key,
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

    if config.project_folder:
        print(f"[info] Project folder configured: {config.project_folder}")
        if not os.path.isdir(config.project_folder):
            print(f"[warn] PROJECT_FOLDER does not exist: {config.project_folder}")
    else:
        print("[info] PROJECT_FOLDER not set — project file tools disabled")

    # ── Fetch server version at startup for auto-update detection ──
    _startup_version = None
    try:
        status = _get_json(f"{config.server_url}/api/status")
        _startup_version = status.get("backend_version")
        if _startup_version:
            print(f"[daemon] Server version at startup: {_startup_version}")
        else:
            print("[daemon] Warning: server /api/status did not return backend_version", file=sys.stderr)
    except RuntimeError as e:
        print(f"[daemon] Warning: could not fetch server version at startup: {e}", file=sys.stderr)

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

    # ── Log transcription file info at startup ──
    try:
        entries = load_transcription_files(config.folder)
        timed = [(ts, txt) for ts, txt in entries if ts is not None]
        if timed:
            max_ts = max(ts for ts, _ in timed)
            cutoff = max_ts - DEFAULT_TRANSCRIPT_MINUTES * 60
            recent = [(ts, txt) for ts, txt in timed if ts >= cutoff and txt.strip()]
            print(f"[transcript] Lines in last {DEFAULT_TRANSCRIPT_MINUTES} min: {len(recent)} (total segments: {len(entries)})")
        else:
            print(f"[transcript] Total segments: {len(entries)} (no timestamps found)")
    except SystemExit:
        print("[transcript] No transcription file found", file=sys.stderr)
    except Exception as e:
        print(f"[transcript] Could not read transcription: {e}", file=sys.stderr)

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
    last_notes_mtime: float = 0.0  # track notes file mtime for re-push on change
    # ── Session stack initialization ──
    sessions_root = config.session_folder.parent if config.session_folder else Path.cwd()
    session_stack = _load_daemon_state(sessions_root)
    current_key_points: list[dict] = []

    if session_stack:
        # Restore from persisted stack
        current_folder = sessions_root / session_stack[-1]["name"]
        current_key_points = _load_key_points(current_folder)
        print(f"[session] Restored stack ({len(session_stack)} sessions), {len(current_key_points)} key points")
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "summary_watermark": 0,
        }]
        current_key_points = _load_key_points(config.session_folder)
        _save_daemon_state(sessions_root, session_stack)
        print(f"[session] Auto-started: {config.session_folder.name}")

    # Sync initial state to server
    try:
        _sync_session_to_server(config, session_stack, current_key_points)
    except Exception as e:
        print(f"[session] Failed to sync initial state: {e}", file=sys.stderr)

    last_summary_at = 0.0  # monotonic time of last summary run
    transcript_state = TranscriptStateManager()

    while True:
        try:
            # ── Heartbeat: update lock file so other instances know we're alive ──
            now = time.monotonic()
            if now - last_heartbeat_at >= _HEARTBEAT_INTERVAL:
                _write_lock()
                last_heartbeat_at = now

            timestamp_appender.tick()

            # ── Check for session management requests ──
            try:
                session_req = _get_json(
                    f"{config.server_url}/api/session/request",
                    config.host_username, config.host_password,
                )
                action = session_req.get("action")
                if action == "start":
                    name = session_req["name"]
                    folder = sessions_root / name
                    folder.mkdir(parents=True, exist_ok=True)
                    new_session = {
                        "name": name,
                        "started_at": datetime.now().isoformat(),
                        "ended_at": None,
                        "summary_watermark": 0,
                    }
                    session_stack.append(new_session)
                    current_key_points = _load_key_points(folder)
                    _save_daemon_state(sessions_root, session_stack)
                    notes_file = _find_notes_in_folder(folder)
                    config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    print(f"[session] Started: {name}")

                elif action == "end" and len(session_stack) > 1:
                    ended = session_stack.pop()
                    ended["ended_at"] = datetime.now().isoformat()
                    ended_folder = sessions_root / ended["name"]
                    _save_key_points(ended_folder, current_key_points)
                    # Restore parent session
                    parent = session_stack[-1]
                    parent_folder = sessions_root / parent["name"]
                    current_key_points = _load_key_points(parent_folder)
                    _save_daemon_state(sessions_root, session_stack)
                    notes_file = _find_notes_in_folder(parent_folder)
                    config = dc_replace(config, session_folder=parent_folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    print(f"[session] Ended: {ended['name']}, restored: {parent['name']}")

                elif action == "rename":
                    new_name = session_req["name"]
                    if session_stack:
                        old_name = session_stack[-1]["name"]
                        new_folder = sessions_root / new_name
                        # Load existing points from new folder FIRST (before overwriting)
                        existing = _load_key_points(new_folder) if new_folder.exists() else []
                        new_folder.mkdir(parents=True, exist_ok=True)
                        if existing:
                            current_key_points = existing
                        else:
                            _save_key_points(new_folder, current_key_points)
                        session_stack[-1]["name"] = new_name
                        _save_daemon_state(sessions_root, session_stack)
                        notes_file = _find_notes_in_folder(new_folder)
                        config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                        _sync_session_to_server(config, session_stack, current_key_points)
                        print(f"[session] Renamed: {old_name} → {new_name}")
            except Exception as e:
                print(f"[session] Request error: {e}", file=sys.stderr)

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

            # ── Auto-update: check if server version changed ──
            if _startup_version:
                try:
                    status = _get_json(f"{config.server_url}/api/status")
                    current_version = status.get("backend_version")
                    if current_version and current_version != _startup_version:
                        print(f"\n[daemon] Server version changed: {_startup_version} → {current_version}")
                        print("[daemon] Exiting for auto-update (exit code 42)...")
                        _LOCK_FILE.unlink(missing_ok=True)
                        sys.exit(EXIT_CODE_UPDATE)
                except RuntimeError:
                    pass  # server unreachable — skip version check this cycle

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

            # Push notes content when file is new or modified
            if config.session_notes:
                try:
                    current_mtime = config.session_notes.stat().st_mtime
                except OSError:
                    current_mtime = 0.0
                notes_changed = current_mtime != last_notes_mtime and current_mtime > 0
                if notes_changed or not server_has_notes:
                    notes_text = read_session_notes(config)
                    if notes_text:
                        _post_json(
                            f"{config.server_url}/api/notes",
                            {"content": notes_text},
                            config.host_username, config.host_password,
                        )
                        last_notes_mtime = current_mtime
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

            # ── Check for debate AI cleanup request ──
            try:
                debate_data = _get_json(
                    f"{config.server_url}/api/debate/ai-request",
                    config.host_username, config.host_password,
                )
                debate_req = debate_data.get("request")
                if debate_req:
                    print(f"\n[daemon] Debate AI cleanup requested: '{debate_req['statement'][:60]}'")
                    try:
                        result = run_debate_ai_cleanup(debate_req, config.api_key, config.model)
                        _post_json(
                            f"{config.server_url}/api/debate/ai-result",
                            result,
                            config.host_username, config.host_password,
                        )
                        n_new = len(result.get("new_arguments", []))
                        n_merges = len(result.get("merges", []))
                        print(f"[daemon] Debate AI done: {n_merges} merges, {n_new} new args")
                    except Exception as e:
                        print(f"[daemon] Debate AI cleanup failed: {e}", file=sys.stderr)
                        # Post empty result so backend advances to prep anyway
                        _post_json(
                            f"{config.server_url}/api/debate/ai-result",
                            {"merges": [], "cleaned": [], "new_arguments": []},
                            config.host_username, config.host_password,
                        )
            except RuntimeError:
                pass  # server unreachable — skip this cycle

            # ── Push transcript stats every 10s ──
            if now - last_transcript_stats_at >= 10.0:
                last_transcript_stats_at = now
                try:
                    entries = load_transcription_files(config.folder)
                    timed = [(ts, txt) for ts, txt in entries if ts is not None]
                    total_lines = len(entries)
                    if timed:
                        max_ts = max(ts for ts, _ in timed)
                        cutoff = max_ts - DEFAULT_TRANSCRIPT_MINUTES * 60
                        recent = [(ts, txt) for ts, txt in timed if ts >= cutoff and txt.strip()]
                        line_count = len(recent)
                        # Convert max_ts (seconds from midnight) to today's ISO time
                        h, rem = divmod(int(max_ts), 3600)
                        m, s = divmod(rem, 60)
                        latest_time = f"{h:02d}:{m:02d}:{s:02d}"
                    else:
                        line_count = 0
                        latest_time = None
                    print(f"[transcript] {line_count} lines in last {DEFAULT_TRANSCRIPT_MINUTES}min (total: {len(entries)} segments, {len(timed)} timed, latest: {latest_time})")
                    _post_json(
                        f"{config.server_url}/api/transcript-status",
                        {"line_count": line_count, "total_lines": total_lines, "latest_ts": latest_time},
                        config.host_username, config.host_password,
                    )
                except SystemExit:
                    pass
                except Exception as e:
                    print(f"[transcript] Error: {e}", file=sys.stderr)

                # ── Push token usage alongside transcript stats ──
                try:
                    _post_json(
                        f"{config.server_url}/api/token-usage",
                        get_usage().to_dict(),
                        config.host_username, config.host_password,
                    )
                except Exception as e:
                    print(f"[daemon] Token usage POST failed: {e}", file=sys.stderr)

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

            # ── On-demand summary generation (session-aware) ──
            now_mono = time.monotonic()
            if force_summary and session_stack:
                current_session = session_stack[-1]
                session_folder = sessions_root / current_session["name"]
                watermark = current_session.get("summary_watermark", 0)
                print(f"[summarizer] Generating summary (on-demand, watermark={watermark})")
                last_summary_at = now_mono
                try:
                    entries = load_transcription_files(config.folder)
                    if entries:
                        # TODO Task 7: use extract_text_for_time_window with session time windows
                        full_text = extract_all_text(entries)
                        if full_text:
                            # Use watermark to compute delta
                            delta_text = full_text[watermark:] if watermark < len(full_text) else None
                            if not delta_text:
                                print("[summarizer] No new transcript content — skipping")
                                continue
                            print(f"[summarizer] Delta: {len(delta_text)} chars (full: {len(full_text)} chars)")

                            last_5 = current_key_points[-5:] if current_key_points else []
                            result = generate_summary(config, last_5, delta_text=delta_text)
                            if result is not None:
                                # Compatibility shim: if generate_summary returns a list, wrap it
                                if isinstance(result, list):
                                    result = {"updated": [], "new": [{"text": p["text"], "source": p.get("source", "discussion"), "time": p.get("time")} for p in result]}

                                # Apply updates
                                for upd in result.get("updated", []):
                                    idx = upd.get("index")
                                    if idx is not None and 0 <= idx < len(current_key_points):
                                        current_key_points[idx] = {
                                            "text": upd["text"],
                                            "source": upd.get("source", "discussion"),
                                            "time": upd.get("time"),
                                        }
                                # Append new points
                                for new_pt in result.get("new", []):
                                    current_key_points.append({
                                        "text": new_pt["text"],
                                        "source": new_pt.get("source", "discussion"),
                                        "time": new_pt.get("time"),
                                    })

                                # Update watermark
                                current_session["summary_watermark"] = len(full_text)

                                # Persist and sync
                                _save_key_points(session_folder, current_key_points)
                                _save_daemon_state(sessions_root, session_stack)
                                _sync_session_to_server(config, session_stack, current_key_points)
                                print(f"[summarizer] {len(current_key_points)} total key points")
                except Exception as e:
                    print(f"[summarizer] Error: {e}", file=sys.stderr)

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
