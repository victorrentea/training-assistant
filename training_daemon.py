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

import hashlib
import json
import os
import re
import signal
import sys
import time

from dataclasses import replace as dc_replace
from datetime import date, datetime, timedelta
from pathlib import Path

from daemon.transcript_timestamps import (
    append_empty_line_then_timestamp,
    infer_template_from_first_line,
)
from quiz_core import (
    config_from_env, find_session_folder, auto_generate, auto_generate_topic, auto_refine,
    post_status, _get_json, _post_json, DAEMON_POLL_INTERVAL, DEFAULT_TRANSCRIPT_MINUTES,
    read_session_notes, load_transcription_files,
)
from daemon.debate_ai import run_debate_ai_cleanup
from daemon.llm_adapter import get_usage
from daemon.summarizer import generate_summary
from daemon.transcript_state import TranscriptStateManager
from daemon.session_transcript import (
    parse_txt_entries_with_datetimes,
    compute_active_windows,
    count_lines_in_windows,
    format_time_ranges,
)
from daemon import log

_LOCK_FILE = Path("/tmp/training_daemon.lock")
_HEARTBEAT_INTERVAL = 1.0  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 10.0  # seconds before heartbeat is considered stale
_TIMESTAMP_INTERVAL_SECONDS = float(os.environ.get("TRANSCRIPT_TIMESTAMP_INTERVAL_SECONDS", "3"))
EXIT_CODE_UPDATE = 42  # signals start.sh to git pull and restart
_KEY_POINTS_FILE = "transcript_discussion.md"
_KEY_POINTS_FILE_LEGACY_MD = "transcript_keypoints.md"
_KEY_POINTS_FILE_LEGACY = "key_points.json"
_DAEMON_STATE_FILENAME = "daemon_state.json"
_BACKUP_DIR = Path.home() / ".training-assistant"
_BACKUP_FILE = _BACKUP_DIR / "state-backup.json"


_DOW_RE = re.compile(r"^([A-Z][a-z]{2})\s+(\d{2}:\d{2})\s+(.+)$")
_FRONTMATTER_WATERMARK_RE = re.compile(r"^watermark:\s*(\d+)")


def _check_daily_timing(now_time=None):
    """Returns 'midnight', 'auto_pause', 'warning', or None based on current time."""
    from datetime import time as _time
    if now_time is None:
        now_time = datetime.now().time()
    # Check midnight first (spans 23:59-00:01)
    if now_time >= _time(23, 59) or now_time < _time(0, 1):
        return "midnight"
    # auto_pause uses threshold (>= 18:00), deduplication prevents re-firing
    if now_time >= _time(18, 0):
        return "auto_pause"
    if now_time >= _time(17, 30):
        return "warning"
    return None


def _load_key_points(session_folder: Path) -> tuple[list[dict], int]:
    """Load key points from session folder. Returns (points, watermark).
    Reads transcript_discussion.md (new) or falls back to transcript_keypoints.md (legacy md)
    or key_points.json (oldest legacy)."""
    md_file = session_folder / _KEY_POINTS_FILE
    legacy_md_file = session_folder / _KEY_POINTS_FILE_LEGACY_MD
    json_file = session_folder / _KEY_POINTS_FILE_LEGACY

    if md_file.exists():
        try:
            lines = md_file.read_text(encoding="utf-8").splitlines()
            watermark = 0
            points = []
            in_frontmatter = False
            seen_open = False
            for line in lines:
                stripped = line.strip()
                if not seen_open and stripped == "---":
                    in_frontmatter = True
                    seen_open = True
                    continue
                if in_frontmatter:
                    if stripped == "---":
                        in_frontmatter = False
                        continue
                    m = _FRONTMATTER_WATERMARK_RE.match(stripped)
                    if m:
                        watermark = int(m.group(1))
                    continue
                if not stripped:
                    continue
                m = _DOW_RE.match(stripped)
                if m:
                    points.append({"text": m.group(3), "time": m.group(2), "source": "discussion"})
                else:
                    points.append({"text": stripped, "source": "discussion"})
            log.info("session", f"Loaded {len(points)} key points from {session_folder.name}")
            return points, watermark
        except Exception as e:
            log.error("session", f"Failed to load key points: {e}")
            return [], 0

    if legacy_md_file.exists():
        try:
            lines = legacy_md_file.read_text(encoding="utf-8").splitlines()
            watermark = 0
            points = []
            in_frontmatter = False
            seen_open = False
            for line in lines:
                stripped = line.strip()
                if not seen_open and stripped == "---":
                    in_frontmatter = True
                    seen_open = True
                    continue
                if in_frontmatter:
                    if stripped == "---":
                        in_frontmatter = False
                        continue
                    m = _FRONTMATTER_WATERMARK_RE.match(stripped)
                    if m:
                        watermark = int(m.group(1))
                    continue
                if not stripped:
                    continue
                m = _DOW_RE.match(stripped)
                if m:
                    points.append({"text": m.group(3), "time": m.group(2), "source": "discussion"})
                else:
                    points.append({"text": stripped, "source": "discussion"})
            log.info("session", f"Loaded {len(points)} key points (legacy md) from {session_folder.name}")
            return points, watermark
        except Exception as e:
            log.error("session", f"Failed to load key points: {e}")
            return [], 0

    if json_file.exists():
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            points = data.get("points", data.get("locked", []) + data.get("draft", []))
            watermark = data.get("watermark", 0)
            log.info("session", f"Loaded {len(points)} key points (legacy) from {session_folder.name}")
            return points, watermark
        except Exception as e:
            log.error("session", f"Failed to load key points: {e}")
            return [], 0

    return [], 0


def _session_start_date(session_entry: dict) -> date | None:
    """Extract the session start date from a session stack entry."""
    try:
        return datetime.fromisoformat(session_entry["started_at"]).date()
    except Exception:
        return None


def _save_key_points(
    session_folder: Path,
    points: list[dict],
    watermark: int = 0,
    session_date: date | None = None,
) -> None:
    """Save key points to transcript_discussion.md with DOW HH:MM prefix per line."""
    try:
        session_folder.mkdir(parents=True, exist_ok=True)

        # Only timed discussion points go to disk; notes-only bullets are ephemeral
        timed = [(p, p["time"]) for p in points if p.get("time")]

        # Sort by time and detect midnight crossings for DOW assignment
        def _mins(t: str) -> int:
            try:
                return int(t[:2]) * 60 + int(t[3:5])
            except Exception:
                return 0

        timed.sort(key=lambda x: _mins(x[1]))

        base_date = session_date or date.today()
        current_date = base_date
        prev_mins: int | None = None
        lines = ["---", f"watermark: {watermark}", "---", ""]

        for point, time_str in timed:
            mins = _mins(time_str)
            # Crossed midnight: new time is significantly smaller than previous
            if prev_mins is not None and mins < prev_mins - 30:
                current_date += timedelta(days=1)
            prev_mins = mins
            dow = current_date.strftime("%a")
            lines.append(f"{dow} {time_str} {point['text']}")

        (session_folder / _KEY_POINTS_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.error("session", f"Failed to save key points: {e}")


def _save_session_state(session_folder: Path, snapshot: dict) -> None:
    """Atomically writes session_state.json to the session folder."""
    path = session_folder / "session_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, default=str, indent=2))
    tmp.replace(path)


def _load_daemon_state(sessions_root: Path) -> dict:
    """Load daemon state. Returns {main: dict|None, talk: dict|None}.
    Migrates old {stack:[...]} format transparently."""
    state_file = sessions_root / _DAEMON_STATE_FILENAME
    empty = {"main": None, "talk": None}
    if not state_file.exists():
        return empty
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("session", f"Failed to load daemon state: {e}")
        return empty
    # Migration: old format had {stack: [...]}
    if "stack" in data and "main" not in data:
        stack = data["stack"]
        active = [s for s in stack if not s.get("ended_at")]
        return {
            "main": {**active[0], "status": "active"} if len(active) >= 1 else None,
            "talk": {**active[1], "status": "active"} if len(active) >= 2 else None,
        }
    return data


def _daemon_state_to_stack(daemon_state: dict) -> list[dict]:
    """Convert {main, talk} daemon state dict to the in-memory session stack list.
    Sessions with status 'ended' are excluded — they are not restored."""
    main = daemon_state.get("main")
    talk = daemon_state.get("talk")
    # If main session is ended, treat as no session at all
    if main and main.get("status") == "ended":
        return []
    stack = []
    if main:
        stack.append(main)
    # If talk session is ended, keep main but discard talk
    if talk and talk.get("status") != "ended":
        stack.append(talk)
    return stack


def _stack_to_daemon_state(stack: list[dict]) -> dict:
    """Convert in-memory session stack list to {main, talk} dict for persistence."""
    def _with_status(s: dict) -> dict:
        paused = any(p.get("to") is None for p in s.get("paused_intervals", []))
        return {**s, "status": "paused" if paused else "active"}
    return {
        "main": _with_status(stack[0]) if len(stack) >= 1 else None,
        "talk": _with_status(stack[1]) if len(stack) >= 2 else None,
    }


def _pause_session(session: dict, now: datetime, reason: str = "explicit") -> None:
    """Add an open pause interval to a session (no-op if already paused)."""
    pauses = session.setdefault("paused_intervals", [])
    if not any(p.get("to") is None for p in pauses):
        pauses.append({"from": now.isoformat(), "to": None, "reason": reason})


def _resume_session(session: dict, now: datetime) -> None:
    """Close the most recent open pause interval on a session."""
    for p in reversed(session.get("paused_intervals", [])):
        if p.get("to") is None:
            p["to"] = now.isoformat()
            return


def _save_daemon_state(sessions_root: Path, daemon_state: dict) -> None:
    """Persist {main, talk} daemon state to disk atomically."""
    try:
        sessions_root.mkdir(parents=True, exist_ok=True)
        path = sessions_root / _DAEMON_STATE_FILENAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(daemon_state, default=str, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.error("session", f"Failed to save daemon state: {e}")


def _find_notes_in_folder(folder: Path) -> Path | None:
    """Find the most recently modified .txt notes file in a session folder."""
    if not folder.exists():
        return None
    txt_files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    return txt_files[-1] if txt_files else None


def _sync_session_to_server(
    config, stack: list[dict], key_points: list[dict],
    session_state: dict | None = None,
) -> None:
    """Push session stack and key points to server.
    If session_state is provided, it is included for a plain restore (no participant disconnect)."""
    daemon_state = _stack_to_daemon_state(stack)
    payload: dict = {"main": daemon_state["main"], "talk": daemon_state["talk"], "key_points": key_points}
    if session_state is not None:
        payload["session_state"] = session_state
    _post_json(
        f"{config.server_url}/api/session/sync",
        payload,
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
        log.error("daemon", message)
        self._startup_error_logged = True

    def start(self) -> None:
        if self.interval_seconds <= 0:
            self._log_startup_error_once(
                "Timestamp appender disabled: INTERVAL_SECONDS must be > 0"
            )
            return

        self._target_file = self._resolve_target_file()
        if self._target_file is None:
            self._log_startup_error_once(
                f"Timestamp appender disabled: no .txt in {self.folder}"
            )
            return

        self._template = infer_template_from_first_line(self._target_file)
        self._next_append_at = time.monotonic()
        self.enabled = True
        log.info("daemon", f"Transcript timestamp appender enabled ({self.interval_seconds:.1f}s) on {self._target_file.name}")

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
            log.error("daemon", f"Timestamp appender stopped: {exc}")
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
        log.info("daemon", f"Another instance is already running (PID {pid}, heartbeat {heartbeat_age:.1f}s ago). Exiting.")
        sys.exit(0)

    if alive and heartbeat_age > _HEARTBEAT_STALE_THRESHOLD:
        # Process exists but heartbeat is stale — something is wrong
        log.error("daemon", f"Previous instance (PID {pid}) is alive but heartbeat is stale ({heartbeat_age:.0f}s ago). Killing it.")
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ProcessLookupError, PermissionError):
            pass

    if not alive:
        # Process is dead — stale lock file from a crash
        log.info("daemon", f"Previous instance (PID {pid}) is dead (crashed?). Cleaning up lock file.")

    _LOCK_FILE.unlink(missing_ok=True)


def run() -> None:
    _check_and_acquire_lock()
    _write_lock()
    log.info("daemon", "🚀 Starting daemon")

    def _cleanup(*_):
        _LOCK_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    config = config_from_env()

    if config.project_folder:
        log.info("daemon", f"Project folder configured: {config.project_folder}")
        if not os.path.isdir(config.project_folder):
            log.error("daemon", f"PROJECT_FOLDER does not exist: {config.project_folder}")
    else:
        log.info("daemon", "PROJECT_FOLDER not set — project file tools disabled")

    # ── Fetch server version at startup for auto-update detection ──
    _startup_version = None
    try:
        status = _get_json(f"{config.server_url}/api/status")
        _startup_version = status.get("backend_version")
        if _startup_version:
            log.info("daemon", f"Server version at startup: {_startup_version}")
        else:
            log.error("daemon", "Server /api/status did not return backend_version")
    except RuntimeError as e:
        log.error("daemon", f"Could not fetch server version at startup: {e}")

    # ── Restore state from backup if server needs it ──
    try:
        status = _get_json(f"{config.server_url}/api/status")
        if status.get("needs_restore"):
            if _BACKUP_FILE.exists():
                log.info("daemon", "Server needs state restore — sending backup...")
                backup_data = json.loads(_BACKUP_FILE.read_text(encoding="utf-8"))
                result = _post_json(
                    f"{config.server_url}/api/state-restore",
                    backup_data,
                    config.host_username, config.host_password,
                )
                log.info("daemon", f"State restore result: {result.get('status', 'ok')}")
            else:
                log.error("daemon", f"Server needs state restore but no backup file found at {_BACKUP_FILE}")
        else:
            log.info("daemon", "Server does not need state restore")
    except Exception as e:
        log.error("daemon", f"State restore check failed: {e}")

    # Detect today's session folder
    sf, sn = find_session_folder(date.today())
    config = dc_replace(config, session_folder=sf, session_notes=sn)
    if sf:
        log.info("session", f"Session folder: {sf.name}")
        log.info("session", f"Notes file: {sn.name if sn else 'NOT FOUND'}")
    else:
        log.error("session", "No session folder found for today")

    # Start background material indexer
    materials_folder_str = os.environ.get("MATERIALS_FOLDER",
        str(Path(__file__).parent / "materials"))
    materials_folder = Path(materials_folder_str).expanduser()
    if materials_folder.exists():
        from daemon.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        log.error("daemon", f"MATERIALS_FOLDER not found: {materials_folder} — indexer disabled")

    # ── Session stack initialization (early — needed for transcript log) ──
    sessions_root = config.session_folder.parent if config.session_folder else Path.cwd()
    session_stack = _daemon_state_to_stack(_load_daemon_state(sessions_root))
    current_key_points: list[dict] = []
    summary_watermark: int = 0

    if session_stack:
        # Restore from persisted stack
        current_folder = sessions_root / session_stack[-1]["name"]
        current_key_points, summary_watermark = _load_key_points(current_folder)
        log.info("session", f"Restored stack ({len(session_stack)} sessions), {len(current_key_points)} key points")
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
        }]
        current_key_points, summary_watermark = _load_key_points(config.session_folder)
        _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
        log.info("session", f"Auto-started: {config.session_folder.name}")

    # ── Log transcription time ranges at startup ──
    try:
        files = sorted(config.folder.glob("*.txt"), key=lambda f: f.stat().st_mtime)
        if files:
            raw = files[-1].read_text(encoding="utf-8", errors="replace")
            stem = files[-1].stem[:8]
            try:
                file_date = date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
            except (ValueError, IndexError):
                file_date = None
            entries = parse_txt_entries_with_datetimes(raw, file_date)
            if session_stack:
                current_session = session_stack[-1]
                windows = compute_active_windows(current_session, datetime.now())
                line_count = count_lines_in_windows(entries, windows)
                log.info("transcript", format_time_ranges(windows, line_count))
            else:
                non_empty = sum(1 for _, txt in entries if txt.strip())
                log.info("transcript", f"{non_empty} lines (no active session)")
        else:
            log.error("transcript", "No transcription file found")
    except Exception as e:
        log.error("transcript", f"Could not read transcription: {e}")

    log.info("daemon", f"Started — polling {config.server_url} every {DAEMON_POLL_INTERVAL}s")

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
    last_transcript_line_count = -1
    last_notes_mtime: float = 0.0  # track notes file mtime for re-push on change
    last_auto_close_date: date | None = None   # prevent double-close on same calendar day
    last_auto_start_date: date | None = None   # prevent double-start on same calendar day
    _timing_fired_date: date | None = None     # date for which timing events were tracked
    _timing_fired_today: set = set()           # timing events already fired today

    # Sync initial state to server — include session_state.json if present in the active folder
    try:
        startup_session_state: dict | None = None
        if session_stack:
            state_file = sessions_root / session_stack[-1]["name"] / "session_state.json"
            if state_file.exists():
                try:
                    startup_session_state = json.loads(state_file.read_text(encoding="utf-8"))
                    log.info("session", f"Loaded session_state.json for restore ({len(startup_session_state)} keys)")
                except Exception as e:
                    log.error("session", f"Failed to read session_state.json: {e}")
        _sync_session_to_server(config, session_stack, current_key_points, startup_session_state)
    except Exception as e:
        log.error("session", f"Failed to sync initial state: {e}")

    last_summary_at = 0.0  # monotonic time of last summary run
    last_snapshot_hash: str | None = None  # hash of last saved state snapshot
    transcript_state = TranscriptStateManager()
    _SAVE_INTERVAL = 5
    # Trigger immediate save on first iteration if a session is already active
    _save_counter = _SAVE_INTERVAL if session_stack else 0

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
                    # Pause the current session while the nested one is active
                    if session_stack:
                        _pause_session(session_stack[-1], datetime.now(), reason="nested")
                    new_session = {
                        "name": name,
                        "started_at": datetime.now().isoformat(),
                        "ended_at": None,
                    }
                    session_stack.append(new_session)
                    current_key_points, summary_watermark = _load_key_points(folder)
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    notes_file = _find_notes_in_folder(folder)
                    config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    log.info("session", f"Started: {name}")

                elif action == "end" and len(session_stack) > 1:
                    ended = session_stack.pop()
                    ended["ended_at"] = datetime.now().isoformat()
                    ended_folder = sessions_root / ended["name"]
                    _save_key_points(ended_folder, current_key_points, summary_watermark, _session_start_date(ended))
                    # Restore parent session and close its nested pause
                    parent = session_stack[-1]
                    _resume_session(parent, datetime.now())
                    parent_folder = sessions_root / parent["name"]
                    current_key_points, summary_watermark = _load_key_points(parent_folder)
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    notes_file = _find_notes_in_folder(parent_folder)
                    config = dc_replace(config, session_folder=parent_folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    log.info("session", f"Ended: {ended['name']}, restored: {parent['name']}")

                elif action == "rename":
                    new_name = session_req["name"]
                    if session_stack:
                        old_name = session_stack[-1]["name"]
                        new_folder = sessions_root / new_name
                        # Load existing points from new folder FIRST (before overwriting)
                        existing_pts, existing_wm = _load_key_points(new_folder) if new_folder.exists() else ([], 0)
                        new_folder.mkdir(parents=True, exist_ok=True)
                        if existing_pts:
                            current_key_points, summary_watermark = existing_pts, existing_wm
                        else:
                            _save_key_points(new_folder, current_key_points, summary_watermark, _session_start_date(session_stack[-1]))
                        session_stack[-1]["name"] = new_name
                        _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                        notes_file = _find_notes_in_folder(new_folder)
                        config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                        _sync_session_to_server(config, session_stack, current_key_points)
                        log.info("session", f"Renamed: {old_name} → {new_name}")

                elif action == "pause" and session_stack:
                    _pause_session(session_stack[-1], datetime.now(), reason="explicit")
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    _sync_session_to_server(config, session_stack, current_key_points)
                    log.info("session", f"Paused: {session_stack[-1]['name']}")

                elif action == "resume" and session_stack:
                    _resume_session(session_stack[-1], datetime.now())
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    log.info("session", f"Resumed: {session_stack[-1]['name']}")

                elif action == "start_talk":
                    now = datetime.now()
                    talk_name = f"{now.strftime('%Y-%m-%d %H:%M')} talk"
                    talk_folder = sessions_root / talk_name
                    talk_folder.mkdir(parents=True, exist_ok=True)

                    # Save current (main) session state immediately before switching
                    current_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
                    if current_folder and current_folder.exists():
                        try:
                            snapshot = _get_json(
                                f"{config.server_url}/api/session/snapshot",
                                config.host_username, config.host_password,
                            )
                            _save_session_state(current_folder, snapshot)
                        except Exception as e:
                            log.error("daemon", f"START TALK: failed to save main snapshot: {e}")

                    # Load talk's existing key points (if folder had prior data)
                    talk_points, talk_wm = _load_key_points(talk_folder)

                    # Load talk's existing session state
                    talk_state = None
                    talk_state_path = talk_folder / "session_state.json"
                    if talk_state_path.exists():
                        try:
                            talk_state = json.loads(talk_state_path.read_text())
                        except Exception:
                            pass

                    # Push new talk session onto stack
                    session_stack.append({
                        "name": talk_name,
                        "started_at": now.isoformat(),
                        "status": "active",
                    })
                    current_key_points, summary_watermark = talk_points, talk_wm
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    notes_file = _find_notes_in_folder(talk_folder)
                    config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                    # Sync to server: mark current participants as paused, restore talk state
                    _post_json(
                        f"{config.server_url}/api/session/sync",
                        {
                            **_stack_to_daemon_state(session_stack),
                            "discussion_points": talk_points,
                            "session_state": talk_state,
                            "action": "start_talk",
                        },
                        config.host_username, config.host_password,
                    )
                    transcript_state.reset()
                    log.info("session", f"START TALK: {talk_name}")

                elif action == "end_talk":
                    if len(session_stack) < 2:
                        log.warning("daemon", "END TALK requested but no talk is active")
                    else:
                        # Save talk state before ending
                        talk_folder = sessions_root / session_stack[-1]["name"]
                        if talk_folder.exists():
                            try:
                                snapshot = _get_json(
                                    f"{config.server_url}/api/session/snapshot",
                                    config.host_username, config.host_password,
                                )
                                _save_session_state(talk_folder, snapshot)
                                _save_key_points(talk_folder, current_key_points, summary_watermark, _session_start_date(session_stack[-1]))
                            except Exception as e:
                                log.error("daemon", f"END TALK: failed to save talk state: {e}")

                        # Pop talk, restore main
                        session_stack.pop()
                        _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))

                        main_folder = sessions_root / session_stack[0]["name"] if session_stack else None
                        current_key_points, summary_watermark = _load_key_points(main_folder) if main_folder else ([], 0)

                        # Load main's saved session state for restore
                        main_state = None
                        if main_folder and (main_folder / "session_state.json").exists():
                            try:
                                main_state = json.loads((main_folder / "session_state.json").read_text())
                            except Exception:
                                pass

                        notes_file = _find_notes_in_folder(main_folder) if main_folder else None
                        config = dc_replace(config, session_folder=main_folder, session_notes=notes_file)

                        # Sync to server: restore main participants, clear talk
                        _post_json(
                            f"{config.server_url}/api/session/sync",
                            {
                                **_stack_to_daemon_state(session_stack),
                                "discussion_points": current_key_points,
                                "session_state": main_state,
                                "action": "end_talk",
                            },
                            config.host_username, config.host_password,
                        )
                        transcript_state.reset()
                        log.info("daemon", f"END TALK: restored main session {session_stack[0]['name'] if session_stack else 'none'}")

                elif action == "create_talk_folder":
                    now = datetime.now()
                    talk_name = f"{now.strftime('%Y-%m-%d %H:%M')} talk"
                    talk_folder = sessions_root / talk_name
                    talk_folder.mkdir(parents=True, exist_ok=True)

                    # Push talk onto stack without disconnecting participants
                    session_stack.append({
                        "name": talk_name,
                        "started_at": now.isoformat(),
                        "status": "active",
                    })
                    talk_points, talk_wm = _load_key_points(talk_folder)
                    current_key_points, summary_watermark = talk_points, talk_wm
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    notes_file = _find_notes_in_folder(talk_folder)
                    config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                    # Sync to server without disconnecting participants (no "action" key)
                    _post_json(
                        f"{config.server_url}/api/session/sync",
                        {
                            **_stack_to_daemon_state(session_stack),
                            "discussion_points": talk_points,
                            "session_state": None,
                        },
                        config.host_username, config.host_password,
                    )
                    log.info("session", f"Created talk folder: {talk_name}")

            except Exception as e:
                log.error("session", f"Request error: {e}")

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
                        log.info("session", f"Detected: {sf.name} / notes: {sn.name if sn else 'none'}")
                    else:
                        log.error("session", "No session folder for today")
                    _session_status_pending = True
                else:
                    _session_status_pending = False
            else:
                _session_status_pending = False

            sf_name = config.session_folder.name if config.session_folder else None
            sn_name = config.session_notes.name if config.session_notes else None

            # ── Working hours enforcement (day-end pause at 20:00, auto-resume at 09:30) ──
            now_wall = datetime.now()
            if session_stack and now_wall.hour >= 20 and last_auto_close_date != today:
                last_auto_close_date = today
                top = session_stack[-1]
                top_folder = sessions_root / top["name"]
                _save_key_points(top_folder, current_key_points, summary_watermark, _session_start_date(top))
                # Pause all active sessions in the stack (day-end pause — not ended, resumes tomorrow)
                for s in session_stack:
                    if s.get("ended_at") is None:
                        _pause_session(s, now_wall, reason="day_end")
                _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                _sync_session_to_server(config, session_stack, current_key_points)
                transcript_state.reset()
                log.info("session", "Auto-paused at 20:00 (end of working hours)")

            elif (session_stack
                    and 9 <= now_wall.hour < 20
                    and last_auto_start_date != today):
                # Resume any open day_end pauses from last night
                top = session_stack[-1]
                open_day_end = any(
                    p.get("to") is None and p.get("reason") == "day_end"
                    for p in top.get("paused_intervals", [])
                )
                if open_day_end:
                    last_auto_start_date = today
                    for s in session_stack:
                        if s.get("ended_at") is None:
                            _resume_session(s, now_wall)
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    log.info("session", f"Auto-resumed at 09:30: {session_stack[-1]['name']}")

            elif (not session_stack
                    and 9 <= now_wall.hour < 20
                    and config.session_folder
                    and last_auto_start_date != today):
                last_auto_start_date = today
                new_session = {
                    "name": config.session_folder.name,
                    "started_at": now_wall.isoformat(),
                    "ended_at": None,
                }
                session_stack.append(new_session)
                current_key_points, summary_watermark = _load_key_points(config.session_folder)
                _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                notes_file = _find_notes_in_folder(config.session_folder)
                config = dc_replace(config, session_notes=notes_file)
                _sync_session_to_server(config, session_stack, current_key_points)
                transcript_state.reset()
                log.info("session", f"Auto-started at 09:30: {config.session_folder.name}")

            # ── Daily timing events (5:30pm warning, 6pm auto-pause, midnight session end) ──
            if _timing_fired_date != today:
                _timing_fired_date = today
                _timing_fired_today = set()

            timing = _check_daily_timing()
            if timing == "warning" and "warning" not in _timing_fired_today:
                _timing_fired_today.add("warning")
                try:
                    _post_json(
                        f"{config.server_url}/api/session/timing_event",
                        {"event": "recording_warning", "minutes_remaining": 30},
                        config.host_username, config.host_password,
                    )
                    log.info("daemon", "Sent recording_warning event at 17:30")
                except Exception as e:
                    log.error("daemon", f"Failed to send warning event: {e}")

            elif timing == "auto_pause" and "auto_pause" not in _timing_fired_today:
                _timing_fired_today.add("auto_pause")
                if session_stack and session_stack[-1].get("status") not in ("ended", "paused"):
                    try:
                        _post_json(
                            f"{config.server_url}/api/session/pause",
                            {},
                            config.host_username, config.host_password,
                        )
                        log.info("daemon", "Auto-paused recording at 18:00")
                    except Exception as e:
                        log.error("daemon", f"Failed to auto-pause: {e}")

            elif timing == "midnight" and "midnight" not in _timing_fired_today:
                _timing_fired_today.add("midnight")
                if session_stack:
                    session_stack[-1]["status"] = "ended"
                    _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                    log.info("daemon", "Session marked as ended at midnight")

            # ── Auto-update: check if server version changed ──
            if _startup_version:
                try:
                    status = _get_json(f"{config.server_url}/api/status")
                    current_version = status.get("backend_version")
                    if current_version and current_version != _startup_version:
                        log.info("daemon", f"Server version changed: {_startup_version} → {current_version}")
                        log.info("daemon", "Exiting for auto-update (exit code 42)...")
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
                log.info("daemon", "Reconnected to server.")
                server_disconnected = False
                _session_status_pending = True

            # ── Restore state if server lost it (e.g. after Railway redeploy) ──
            if data.get("needs_restore"):
                if _BACKUP_FILE.exists():
                    log.info("daemon", "Server needs state restore — sending backup...")
                    backup_data = json.loads(_BACKUP_FILE.read_text(encoding="utf-8"))
                    result = _post_json(
                        f"{config.server_url}/api/state-restore",
                        backup_data,
                        config.host_username, config.host_password,
                    )
                    log.info("daemon", f"State restore result: {result.get('status', 'ok')}")
                else:
                    log.error("daemon", "Server needs state restore but no backup file found")

            # ── Push session info when changed, on reconnect, or if server lost it ──
            server_has_session = data.get("session_folder") is not None
            server_has_notes = data.get("has_notes_content", False)
            server_has_key_points = data.get("has_key_points", False)
            if _session_status_pending or (sf_name and not server_has_session):
                post_status("ready", "Agent ready.", config,
                            session_folder=sf_name, session_notes=sn_name)

            # Re-sync key points when server lost them (e.g. after backend restart)
            if current_key_points and not server_has_key_points:
                try:
                    _sync_session_to_server(config, session_stack, current_key_points)
                except Exception as e:
                    log.error("session", f"Failed to re-sync key points: {e}")

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
                    log.info("daemon", f"Topic request: '{topic}'")
                    result = auto_generate_topic(topic, config)
                else:
                    minutes = minutes or config.minutes
                    log.info("daemon", f"Transcript request: last {minutes} min")
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
                    log.info("daemon", f"Refine request: target={target}")
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
                    log.info("daemon", f"Debate AI cleanup requested: '{debate_req['statement'][:60]}'")
                    try:
                        result = run_debate_ai_cleanup(debate_req, config.api_key, config.model)
                        _post_json(
                            f"{config.server_url}/api/debate/ai-result",
                            result,
                            config.host_username, config.host_password,
                        )
                        n_new = len(result.get("new_arguments", []))
                        n_merges = len(result.get("merges", []))
                        log.info("daemon", f"Debate AI done: {n_merges} merges, {n_new} new args")
                    except Exception as e:
                        log.error("daemon", f"Debate AI cleanup failed: {e}")
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
                        h, rem = divmod(int(max_ts), 3600)
                        m, _ = divmod(rem, 60)
                        latest_time = f"{h}h{m:02d}m"
                    else:
                        line_count = 0
                        latest_time = None
                    if line_count != last_transcript_line_count:
                        log.info("transcript", f"{line_count} lines, latest={latest_time}")
                        last_transcript_line_count = line_count
                    _post_json(
                        f"{config.server_url}/api/transcript-status",
                        {"line_count": line_count, "total_lines": total_lines, "latest_ts": latest_time},
                        config.host_username, config.host_password,
                    )
                except SystemExit:
                    pass
                except Exception as e:
                    log.error("transcript", f"Error: {e}")

                # ── Push token usage alongside transcript stats ──
                try:
                    _post_json(
                        f"{config.server_url}/api/token-usage",
                        get_usage().to_dict(),
                        config.host_username, config.host_password,
                    )
                except Exception as e:
                    log.error("daemon", f"Token usage POST failed: {e}")

            # ── Snapshot state for backup ──
            try:
                snapshot = _get_json(
                    f"{config.server_url}/api/state-snapshot",
                    config.host_username, config.host_password,
                )
                snapshot_json = json.dumps(snapshot, sort_keys=True)
                snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
                if snapshot_hash != last_snapshot_hash:
                    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                    tmp_file = _BACKUP_FILE.with_suffix(".tmp")
                    tmp_file.write_text(snapshot_json, encoding="utf-8")
                    os.rename(str(tmp_file), str(_BACKUP_FILE))
                    last_snapshot_hash = snapshot_hash
                    s = snapshot.get("state", snapshot)
                    parts = [f"{len(s.get('participant_names', {}))} participants"]
                    if s.get("qa_questions"):
                        parts.append(f"{len(s['qa_questions'])} Q&As")
                    if s.get("wordcloud_words"):
                        parts.append(f"{len(s['wordcloud_words'])} words in cloud")
                    if s.get("debate_arguments"):
                        parts.append(f"{len(s['debate_arguments'])} debate args")
                    if s.get("votes"):
                        parts.append(f"{len(s['votes'])} votes")
                    if s.get("summary_points"):
                        parts.append(f"{len(s['summary_points'])} summary pts")
                    log.info("daemon", f"State backup: {', '.join(parts)}")
            except Exception as e:
                log.error("daemon", f"State snapshot failed: {e}")

            # ── Check for full-reset / forced summary request ──
            # (full-reset now behaves the same as force — always full regeneration)
            try:
                reset_data = _get_json(
                    f"{config.server_url}/api/summary/full-reset",
                    config.host_username, config.host_password,
                )
                if reset_data.get("requested"):
                    log.info("summarizer", "Full reset — triggering regeneration")
            except Exception:
                pass

            force_summary = False
            try:
                force_data = _get_json(
                    f"{config.server_url}/api/summary/force",
                    config.host_username, config.host_password,
                )
                force_summary = force_data.get("requested", False)
            except Exception:
                pass

            # ── On-demand summary generation (incremental when possible) ──
            now_mono = time.monotonic()
            if force_summary and session_stack:
                current_session = session_stack[-1]
                session_folder = sessions_root / current_session["name"]
                session_date = _session_start_date(current_session)
                incremental = summary_watermark > 0 and bool(current_key_points)
                last_summary_at = now_mono
                try:
                    result = generate_summary(
                        config,
                        existing_points=current_key_points if incremental else None,
                        since_entry=summary_watermark if incremental else 0,
                        session_start_date=session_date,
                    )
                    if result is not None:
                        new_pts = result["new"]
                        summary_watermark = result["watermark"]
                        if incremental:
                            current_key_points = current_key_points + new_pts
                        else:
                            current_key_points = new_pts
                        _save_key_points(session_folder, current_key_points, summary_watermark, session_date)
                        _save_daemon_state(sessions_root, _stack_to_daemon_state(session_stack))
                        _sync_session_to_server(config, session_stack, current_key_points)
                        log.info("summarizer", f"Key points: {len(current_key_points)} total (+{len(new_pts)} new)")
                except Exception as e:
                    log.error("summarizer", f"Error: {e}")

            # ── Periodic session state snapshot save ──
            _save_counter += 1
            if _save_counter >= _SAVE_INTERVAL:
                _save_counter = 0
                current_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
                if current_folder and current_folder.exists():
                    try:
                        resp = _get_json(
                            f"{config.server_url}/api/session/snapshot",
                            config.host_username, config.host_password,
                        )
                        _save_session_state(current_folder, resp)
                    except Exception as e:
                        log.error("daemon", f"Failed to save session snapshot: {e}")

        except RuntimeError as e:
            if not server_disconnected:
                log.error("daemon", f"Server unreachable: {e}")
                server_disconnected = True
        except KeyboardInterrupt:
            _LOCK_FILE.unlink(missing_ok=True)
            log.info("daemon", "Stopped.")
            return
        except Exception as e:
            # Keep daemon alive for unexpected transient errors; loop retries.
            log.error("daemon", f"Unexpected error (will retry): {e}")
        time.sleep(DAEMON_POLL_INTERVAL)


if __name__ == "__main__":
    run()
