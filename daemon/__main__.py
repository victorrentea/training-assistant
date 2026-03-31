"""Host Daemon — main orchestrator.

Run as: python3 -m daemon
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import replace as dc_replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from daemon import log
from daemon.config import (
    config_from_env,
    find_session_folder,
    read_session_notes,
    DAEMON_POLL_INTERVAL,
    DEFAULT_TRANSCRIPT_MINUTES,
)
from daemon.http import _get_json
from daemon.llm.adapter import get_usage
from daemon.quiz.history import auto_generate, auto_generate_topic, auto_refine
from daemon.quiz.poll_api import post_status
from daemon.debate.ai_cleanup import run_debate_ai_cleanup
from daemon.summary.loop import run_summary_cycle, load_key_points, save_key_points
from daemon.transcript.loop import TranscriptNormalizerRunner
from daemon.transcript.whisper_runner import WhisperTranscriptionRunner
from daemon.transcript.loader import load_transcription_files
from daemon.transcript.query import load_normalized_entries
from daemon.transcript.session import compute_active_windows, format_startup_log
from daemon.transcript.state import TranscriptStateManager
from daemon.slides.loop import SlidesPollingRunner
from daemon.materials.mirror import MaterialsMirrorRunner
from daemon.ws_client import DaemonWsClient
from daemon.session_state import (
    GLOBAL_STATE_FILENAME,
    resolve_materials_folder,
load_daemon_state,
    daemon_state_to_stack,
    stack_to_daemon_state,
    save_daemon_state,
    load_session_meta,
    save_session_meta,
    find_session_folder_by_id,
    session_meta_to_stack,
    pause_session,
    resume_session,
    session_start_date,
    save_session_state,
    find_notes_in_folder,
    sync_session_to_server,
    load_slides_manifest,
    set_current_session_id,
)
from daemon.lock import (
    check_and_acquire_lock,
    write_lock,
    install_signal_handlers,
    cleanup_lock,
    _LOCK_FILE,
    _HEARTBEAT_INTERVAL,
)
from daemon.email_notify import notify as email_notify
from daemon.adapters.loader import adapter as _platform

EXIT_CODE_UPDATE = 42  # signals start.sh to git pull and restart
_BACKUP_DIR = Path.home() / ".training-assistant"
_BACKUP_FILE = _BACKUP_DIR / "state-backup.json"

# ── PowerPoint helpers ─────────────────────────────────────────────────────────

_PPT_UNMAPPED_PRESENTATIONS_ALERTED: set[str] = set()


def _coerce_slide_number(value) -> int:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "missing value":
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _read_session_id_from_session_folder(folder: Path) -> str | None:
    path = folder / "session_state.json"
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    sid = data.get("session_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None


def _build_session_folders_payload(sessions_root: Path) -> list[dict[str, str | None]]:
    return [
        {"name": folder.name, "session_id": _read_session_id_from_session_folder(folder)}
        for folder in sorted((f for f in sessions_root.iterdir() if f.is_dir()), key=lambda p: p.name, reverse=True)
    ]


def _sessions_root_from_env() -> Path:
    return Path(
        os.environ.get(
            "SESSIONS_FOLDER",
            str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
        )
    ).expanduser()


def _resolve_session_folder_from_state(
    sessions_root: Path,
    session_stack: list[dict],
    detected_folder: Path | None,
    detected_notes: Path | None,
) -> tuple[Path | None, Path | None, str]:
    """Resolve active session folder source: daemon stack first, then today detection fallback."""
    if session_stack:
        active_name = session_stack[-1].get("name")
        if active_name:
            active_folder = sessions_root / active_name
            if active_folder.exists() and active_folder.is_dir():
                return active_folder, find_notes_in_folder(active_folder), "stack"
            log.error(
                "session",
                f"Active session folder missing on disk: {active_name}; fallback to today detection",
            )
    if detected_folder:
        return detected_folder, detected_notes, "today"
    return None, None, "none"


_RAW_TRANSCRIPT_TXT_RE = re.compile(r"^(\d{8})\s+\d{4}\b.*\.txt$", re.IGNORECASE)


# def _sync_audiohijack_language(config) -> bool:  # disabled — no longer using Audio Hijack
#     lang = _platform.read_audiohijack_language()
#     if not lang:
#         log.error("daemon", "Could not read AudioHijack language from plist")
#         return False
#     from daemon.quiz.poll_api import _ws_client as _ws
#     if _ws and _ws.send({"type": "transcription_language_status", "language": lang}):
#         pass
#     else:
#         from daemon.http import _post_json
#         _post_json(
#             f"{config.server_url}/api/transcription-language/status",
#             {"language": lang},
#             config.host_username, config.host_password,
#         )
#     log.info("daemon", f"AudioHijack language synced: {lang}")
#     return True


def _raw_transcript_dates(folder: Path) -> set[date]:
    """Return distinct dates found in raw Audio Hijack transcript filenames."""
    dates: set[date] = set()
    if not folder.exists() or not folder.is_dir():
        return dates
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        match = _RAW_TRANSCRIPT_TXT_RE.match(entry.name)
        if not match:
            continue
        ds = match.group(1)
        try:
            dates.add(date(int(ds[:4]), int(ds[4:6]), int(ds[6:8])))
        except ValueError:
            continue
    return dates


def _should_restart_for_missing_today_raw(folder: Path, today: date) -> bool:
    """
    Restart trigger:
    - no raw transcript file for today
    - at least one file for yesterday
    - latest available raw date is yesterday
    """
    dates = _raw_transcript_dates(folder)
    if not dates or today in dates:
        return False
    yesterday = today - timedelta(days=1)
    if yesterday not in dates:
        return False
    return max(dates) == yesterday




def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "slide"


def _normalize_slide_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", Path(str(value or "")).stem.lower())


def _presentation_alert_key(value: str) -> str:
    normalized = _normalize_slide_match_key(value)
    if normalized:
        return normalized
    return str(value or "").strip().lower()


def _iter_catalog_items(raw) -> list[dict]:
    if isinstance(raw, dict):
        if isinstance(raw.get("decks"), list):
            return raw["decks"]
        if isinstance(raw.get("slides"), list):
            return raw["slides"]
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _resolve_presentation_slide_target(
    presentation_name: str,
    server_url: str,
    catalog_file: Path | None,
) -> dict:
    normalized_name = _normalize_slide_match_key(presentation_name)
    server_base = server_url.rstrip("/")

    if catalog_file and catalog_file.exists():
        try:
            raw = json.loads(catalog_file.read_text(encoding="utf-8"))
            seen_slugs: set[str] = set()
            for entry in _iter_catalog_items(raw):
                source_value = str(entry.get("source") or "").strip()
                if not source_value:
                    continue
                source = Path(source_value).expanduser()
                target_pdf = str(entry.get("target_pdf") or "").strip()
                if not target_pdf:
                    target_pdf = f"{source.stem}.pdf"
                if not target_pdf.lower().endswith(".pdf"):
                    target_pdf += ".pdf"
                explicit_slug = str(entry.get("slug") or "").strip().lower()
                slug = explicit_slug or _slugify(Path(target_pdf).stem)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                aliases = {
                    source.name,
                    source.stem,
                    str(entry.get("title") or "").strip(),
                    str(entry.get("name") or "").strip(),
                    Path(target_pdf).stem,
                }
                normalized_aliases = {_normalize_slide_match_key(alias) for alias in aliases if alias}
                if normalized_name and normalized_name in normalized_aliases:
                    return {
                        "slug": slug,
                        "url": f"{server_base}/api/slides/file/{slug}",
                        "target_pdf": target_pdf,
                        "matched": True,
                    }
        except Exception as e:
            log.error("ppt", f"Failed reading slides catalog map: {e}")

    fallback_slug = _slugify(Path(presentation_name).stem)
    return {
        "slug": fallback_slug,
        "url": f"{server_base}/api/slides/file/{fallback_slug}",
        "target_pdf": f"{Path(presentation_name).stem}.pdf",
        "matched": False,
    }


def _ppt_slide_key(state: dict | None) -> tuple | None:
    """Extract (presentation, participant_page) — what participants actually see."""
    if state is None:
        return None
    raw_slide = _coerce_slide_number(state.get("slide"))
    is_presenting = bool(state.get("presenting", False))
    participant_page = max(1, raw_slide - 1) if is_presenting else raw_slide
    return (state.get("presentation"), participant_page)


def _sync_powerpoint_slide_to_server(main_config, slides_cfg, ppt_state: dict | None, ws_client) -> None:
    if ppt_state is None:
        ws_client.send({"type": "slides_clear"})
        return

    catalog_file = getattr(slides_cfg, "catalog_file", None) if slides_cfg else None
    target = _resolve_presentation_slide_target(
        presentation_name=ppt_state.get("presentation", ""),
        server_url=main_config.server_url,
        catalog_file=catalog_file,
    )
    presentation_name = str(ppt_state.get("presentation") or "").strip()
    alert_key = _presentation_alert_key(presentation_name)
    is_matched = bool(target.get("matched", True))
    if not is_matched:
        if alert_key and alert_key not in _PPT_UNMAPPED_PRESENTATIONS_ALERTED:
            _PPT_UNMAPPED_PRESENTATIONS_ALERTED.add(alert_key)
            _platform.beep()
            message = "Presentation inaccessible for participants."
            if presentation_name:
                message = f"{message} ({presentation_name})"
            ws_client.send({"type": "quiz_status", "status": "error", "message": message})
            log.error("ppt", message)
        ws_client.send({"type": "slides_clear"})
        return

    if alert_key:
        _PPT_UNMAPPED_PRESENTATIONS_ALERTED.discard(alert_key)

    raw_slide = _coerce_slide_number(ppt_state.get("slide"))
    is_presenting = bool(ppt_state.get("presenting", False))
    current_page = max(1, raw_slide - 1) if is_presenting else raw_slide
    payload = {
        "type": "slides_current",
        "url": target["url"],
        "slug": target["slug"],
        "source_file": ppt_state.get("presentation"),
        "presentation_name": ppt_state.get("presentation"),
        "current_page": current_page,
    }
    ws_client.send(payload)


def _send_global_state_saved_ack(
    ws_client,
    session_req: dict | None,
    action: str | None,
    persisted: bool,
    session_id: str | None,
) -> None:
    if not session_req:
        return
    request_id = str(session_req.get("request_id") or "").strip()
    if not request_id:
        return
    ws_client.send({
        "type": "global_state_saved",
        "request_id": request_id,
        "action": action,
        "persisted": persisted,
        "session_id": session_id,
        "global_state_file": GLOBAL_STATE_FILENAME,
    })


def _bind_initial_session_folder(config, sessions_root: Path, session_stack: list[dict]) -> tuple[object, str]:
    """Resolve and log session folder binding at daemon startup."""
    today_folder = today_notes = None
    if not session_stack:
        today_folder, today_notes = find_session_folder(date.today())
    resolved_folder, resolved_notes, resolved_source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_stack=session_stack,
        detected_folder=today_folder,
        detected_notes=today_notes,
    )
    config = dc_replace(config, session_folder=resolved_folder, session_notes=resolved_notes)
    if resolved_folder:
        source_msg = "daemon state" if resolved_source == "stack" else "today detection"
        log.info("session", f"Session folder from {source_msg}: {resolved_folder.name}")
        log.info("session", f"Notes file: {resolved_notes.name if resolved_notes else 'NOT FOUND'}")
    else:
        log.info("session", "No session folder found for today")
    return config, resolved_source


def _refresh_session_folder_binding(
    config,
    sessions_root: Path,
    session_stack: list[dict],
    today: date,
    last_detected_date: date | None,
    last_session_check_at: float,
    now_mono: float,
) -> tuple[object, date | None, float, bool]:
    """Periodic session-folder refresh: prefer active stack, fallback to today detection when stack is empty."""
    notes_missing = config.session_notes is None
    date_changed = today != last_detected_date
    session_recheck_due = notes_missing and (now_mono - last_session_check_at >= 5.0)
    if not (date_changed or session_recheck_due):
        return config, last_detected_date, last_session_check_at, False

    last_session_check_at = now_mono
    detected_sf = detected_sn = None
    if not session_stack:
        detected_sf, detected_sn = find_session_folder(today)

    sf, sn, source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_stack=session_stack,
        detected_folder=detected_sf,
        detected_notes=detected_sn,
    )
    changed = (sf != config.session_folder or sn != config.session_notes)
    if changed or date_changed:
        config = dc_replace(config, session_folder=sf, session_notes=sn)
        last_detected_date = today
        if sf:
            if source == "stack":
                log.info("session", f"Active session folder: {sf.name} / notes: {sn.name if sn else 'none'}")
            else:
                log.info("session", f"Detected: {sf.name} / notes: {sn.name if sn else 'none'}")
        else:
            log.info("session", "No session folder for today")
        return config, last_detected_date, last_session_check_at, True
    return config, last_detected_date, last_session_check_at, False


# ── Main run loop ──────────────────────────────────────────────────────────────

def run() -> None:
    check_and_acquire_lock()
    write_lock()
    install_signal_handlers()

    config = config_from_env()
    log.info("daemon", f"🚀 Starting — connecting to {config.server_url}")

    # ── Initialize WebSocket client for backend communication ──
    ws_client = DaemonWsClient()
    _pending_requests: dict[str, dict] = {}  # msg_type → data, populated by WS handlers, consumed by main loop

    def _ws_handler(msg_type: str):
        def handler(data):
            _pending_requests[msg_type] = data
        return handler

    ws_client.register_handler("quiz_request", _ws_handler("quiz_request"))
    ws_client.register_handler("quiz_refine", _ws_handler("quiz_refine"))
    ws_client.register_handler("debate_ai_request", _ws_handler("debate_ai_request"))
    ws_client.register_handler("summary_force", _ws_handler("summary_force"))
    ws_client.register_handler("summary_full_reset", _ws_handler("summary_full_reset"))
    ws_client.register_handler("state_snapshot_result", _ws_handler("state_snapshot_result"))
    ws_client.register_handler("session_snapshot_result", _ws_handler("session_snapshot_result"))
    ws_client.register_handler("session_request", _ws_handler("session_request"))
    ws_client.register_handler("transcription_language_request", _ws_handler("transcription_language_request"))

    # Set ws_client on modules that send results back via WS
    from daemon.quiz.poll_api import set_ws_client as set_poll_ws
    from daemon.session_state import set_ws_client as set_session_ws
    set_poll_ws(ws_client)
    set_session_ws(ws_client)

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
                log.info("daemon", "Server needs state restore — sending backup (will use WS once connected)...")
                # Deferred: restore will be sent via WS after ws_client connects
            else:
                log.error("daemon", f"Server needs state restore but no backup file found at {_BACKUP_FILE}")
        else:
            log.info("daemon", "Server does not need state restore")
    except Exception as e:
        log.error("daemon", f"State restore check failed: {e}")

    # Start background material indexer
    materials_folder = resolve_materials_folder()
    if materials_folder is not None:
        from daemon.rag.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        raw = os.environ.get("MATERIALS_FOLDER", "").strip() or "<auto-detect>"
        log.error("daemon", f"MATERIALS_FOLDER not found (MATERIALS_FOLDER={raw}) — indexer disabled")

    # ── Session stack initialization (early — needed for transcript log) ──
    sessions_root = _sessions_root_from_env()
    log.info("session", f"Sessions root: {sessions_root}")
    _raw_state = load_daemon_state(sessions_root)
    _active_session_id: str | None = None
    session_stack: list[dict] = []

    if "main" in _raw_state or "stack" in _raw_state:
        # Old format — migrate: write session_meta.json per folder, then use new format going forward
        if "stack" in _raw_state:
            _stack_items = _raw_state["stack"]
            _active = [s for s in _stack_items if not s.get("ended_at")]
            _old_state = {
                "main": {**_active[0], "status": "active"} if len(_active) >= 1 else None,
                "talk": {**_active[1], "status": "active"} if len(_active) >= 2 else None,
            }
        else:
            _old_state = _raw_state
        _active_session_id = _raw_state.get("session_id")
        session_stack = daemon_state_to_stack(_old_state)
        if session_stack:
            _main_folder = sessions_root / session_stack[0]["name"]
            if _main_folder.exists() and _main_folder.is_dir():
                _meta = {
                    "session_id": _active_session_id,
                    "started_at": session_stack[0].get("started_at"),
                    "paused_intervals": session_stack[0].get("paused_intervals", []),
                }
                if len(session_stack) >= 2:
                    _meta["talk"] = session_stack[1]
                save_session_meta(_main_folder, _meta)
        log.info("session", "Migrated old daemon state format to session_meta.json")
    elif "active_session_id" in _raw_state:
        # New format — find folder by session_id, load session_meta.json
        _active_session_id = _raw_state.get("active_session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                _meta = load_session_meta(_active_folder)
                session_stack = session_meta_to_stack(_meta, _active_folder.name)

    config, _ = _bind_initial_session_folder(config, sessions_root, session_stack)
    current_key_points: list[dict] = []
    summary_watermark: int = 0

    def _do_save_daemon_state():
        """Save global state (active_session_id only) and session metadata to folder."""
        nonlocal _active_session_id
        global_state = {"active_session_id": _active_session_id} if _active_session_id else {}
        save_daemon_state(sessions_root, global_state)
        if session_stack:
            _main_folder = sessions_root / session_stack[0]["name"]
            _meta = {
                "session_id": _active_session_id,
                "started_at": session_stack[0].get("started_at"),
                "paused_intervals": session_stack[0].get("paused_intervals", []),
            }
            if len(session_stack) >= 2:
                _talk = session_stack[1]
                _meta["talk"] = {
                    **_talk,
                    "status": "paused" if any(p.get("to") is None for p in _talk.get("paused_intervals", [])) else "active",
                }
            save_session_meta(_main_folder, _meta)

    if session_stack:
        # Restore from persisted stack
        current_folder = config.session_folder or (sessions_root / session_stack[-1]["name"])
        current_key_points, summary_watermark = load_key_points(current_folder)
        log.info("session", f"Restored stack ({len(session_stack)} sessions), {len(current_key_points)} key points")
        log.info("session", f"Found active session: {session_stack[-1]['name']}")
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
        }]
        current_key_points, summary_watermark = load_key_points(config.session_folder)
        _do_save_daemon_state()
        log.info("session", f"Found active session: {config.session_folder.name}")
    else:
        log.info("session", "Found active session: <NONE>")

    # ── Log transcription time ranges at startup ──
    try:
        since_date = session_start_date(session_stack[-1]) if session_stack else None
        entries_dt = load_normalized_entries(config.folder, since_date=since_date)
        if entries_dt:
            entries = [(dt, txt) for dt, txt in entries_dt]
            if session_stack:
                current_session = session_stack[-1]
                now = datetime.now()
                windows = compute_active_windows(current_session, now)
                is_ongoing = (
                    current_session.get("ended_at") is None
                    and all(p.get("to") for p in current_session.get("paused_intervals", []))
                )
                log.info("transcript", format_startup_log(
                    entries, windows, summary_watermark, is_ongoing,
                    session_start_date(current_session) or now.date(),
                    now.date(),
                ))
            else:
                non_empty = sum(1 for _, txt in entries if txt.strip())
                log.info("transcript", f"{non_empty} lines (no active session)")
        else:
            log.error("transcript", "No normalized transcription file found")
    except Exception as e:
        log.error("transcript", f"Could not read transcription: {e}")

    # transcript_normalizer = TranscriptNormalizerRunner(config.folder)  # disabled: replaced by Whisper live transcription
    # transcript_normalizer.start()
    whisper_runner = WhisperTranscriptionRunner(config.folder)
    whisper_runner.start()
    slides_runner = SlidesPollingRunner(config)
    slides_runner.start()
    materials_mirror = MaterialsMirrorRunner(config)
    materials_mirror.start()
    slides_runner.set_ws_sender(lambda msg: ws_client.send(msg))

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
    last_slides_payload_hash: str | None = None
    last_powerpoint_state: dict | None = None
    last_powerpoint_error: str | None = None
    # last_lang_sync_date: date | None = None    # disabled — no longer using Audio Hijack
    # last_hijack_restart_for_missing_today: date | None = None  # disabled — no longer using Audio Hijack
    last_raw_transcript_guard_check_at: float = 0.0
    _RAW_TRANSCRIPT_GUARD_INTERVAL: float = 30.0
    slides_log: list[dict] = []        # {file, slide, first_seen_at, first_seen_hhmm, seconds_spent}
    git_repos: list[dict] = []         # {project, path, branch, seconds_spent}
    last_intellij_probe_at: float = 0.0
    _INTELLIJ_PROBE_INTERVAL: float = float(os.environ.get("DAEMON_INTELLIJ_PROBE_INTERVAL_SECONDS", "5.0"))  # probe IntelliJ every 5 seconds
    last_ppt_probe_at: float = 0.0
    _PPT_PROBE_INTERVAL: float = float(os.environ.get("DAEMON_PPT_PROBE_INTERVAL_SECONDS", "3.0"))      # poll PowerPoint for current slide every 3s
    ppt_state: dict | None = None     # last known PowerPoint state (persisted between probe ticks)
    ppt_error: str | None = None      # last known probe error
    last_ppt_track_at: float = 0.0
    _PPT_TRACK_INTERVAL: float = float(os.environ.get("DAEMON_PPT_TRACK_INTERVAL_SECONDS", "5.0"))       # accumulate slide time every 5 seconds
    _last_activity_log_key: tuple = (0, 0)  # (slides_count, git_count) — detect changes

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
        sync_session_to_server(config, session_stack, current_key_points, startup_session_state, slides_log=slides_log, git_repos=git_repos)
    except Exception as e:
        log.error("session", f"Initial sync failed: {e}")

    # ── Sync AudioHijack language to server at startup — disabled ──
    # try:
    #     _sync_audiohijack_language(config)
    #     last_lang_sync_date = date.today()
    # except Exception as e:
    #     log.error("daemon", f"Failed to sync AudioHijack language at startup: {e}")

    last_summary_at = 0.0  # monotonic time of last summary run
    last_snapshot_hash: str | None = None  # hash of last saved state snapshot
    last_state_backup_log: str | None = None  # last emitted state-backup log line (dedupe consecutive repeats)
    transcript_state = TranscriptStateManager()
    # Push session folders list to backend on every (re)connect
    def _push_session_folders():
        if not sessions_root.exists():
            return
        folders = _build_session_folders_payload(sessions_root)
        ws_client.send({"type": "session_folders", "folders": folders})
    ws_client.on_connect(_push_session_folders)

    # Re-sync active session state to backend on every (re)connect (e.g. after backend restart)
    def _sync_session_on_reconnect():
        if not session_stack:
            return
        reconnect_session_state: dict | None = None
        state_file = sessions_root / session_stack[-1]["name"] / "session_state.json"
        if state_file.exists():
            try:
                reconnect_session_state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception as e:
                log.error("session", f"Failed to read session_state.json on reconnect: {e}")
        try:
            sync_session_to_server(config, session_stack, current_key_points, reconnect_session_state, slides_log=slides_log, git_repos=git_repos)
            log.info("session", f"Re-synced session '{session_stack[-1]['name']}' to backend on reconnect")
        except Exception as e:
            log.error("session", f"Session re-sync on reconnect failed: {e}")
    ws_client.on_connect(_sync_session_on_reconnect)

    ws_client.start()

    try:
        while True:
            # ── Drain pending WS messages (handlers run on main thread) ──
            ws_client.drain_queue()

            # ── Heartbeat: update lock file so other instances know we're alive ──
            try:
                now = time.monotonic()
                if now - last_heartbeat_at >= _HEARTBEAT_INTERVAL:
                    write_lock()
                    last_heartbeat_at = now

                # transcript_normalizer.tick()  # disabled: replaced by Whisper live transcription
                slides_runner.tick()
                materials_mirror.tick()

                # ── Detect active PowerPoint presentation/slide via AppleScript ──
                _ppt_now = time.monotonic()
                if _ppt_now - last_ppt_probe_at >= _PPT_PROBE_INTERVAL:
                    last_ppt_probe_at = _ppt_now
                    ppt_state, ppt_error = _platform.probe_powerpoint(timeout_seconds=5.0)
                    if ppt_error:
                        log.error("ppt", f"osascript failed: {ppt_error}")
                        last_powerpoint_error = ppt_error
                    else:
                        if last_powerpoint_error is not None:
                            log.info("ppt", "osascript recovered")
                            last_powerpoint_error = None
                        if ppt_state != last_powerpoint_state:
                            was_presenting = bool((last_powerpoint_state or {}).get("presenting", False))
                            slide_key_changed = _ppt_slide_key(ppt_state) != _ppt_slide_key(last_powerpoint_state)
                            last_powerpoint_state = ppt_state
                            if slide_key_changed:
                                if ppt_state is None:
                                    log.info("ppt", "No active PowerPoint presentation")
                                else:
                                    ppt_stem = Path(ppt_state['presentation']).stem
                                    raw_slide = _coerce_slide_number(ppt_state.get("slide"))
                                    is_presenting = bool(ppt_state.get("presenting", False))
                                    participant_page = max(1, raw_slide - 1) if is_presenting else raw_slide
                                    if was_presenting and not is_presenting:
                                        log.info("ppt", f"📽️ Exited fullscreen — {ppt_stem}:{raw_slide} → :{participant_page}")
                                    else:
                                        fullscreen_flag = " [fullscreen]" if is_presenting else " [normal]"
                                        log.info("ppt", f"📽️ Slide: {ppt_stem}:{raw_slide}{fullscreen_flag} → :{participant_page}")
                                try:
                                    _sync_powerpoint_slide_to_server(config, slides_runner._slides_config, ppt_state, ws_client)
                                except Exception as e:
                                    log.error("ppt", f"Failed to sync slides current to server: {e}")

                # ── Track slides log from PowerPoint state (foreground only, every 5s) ──
                _now_mono = time.monotonic()
                if not ppt_error and ppt_state and ppt_state.get("frontmost", True) and _now_mono - last_ppt_track_at >= _PPT_TRACK_INTERVAL:
                    last_ppt_track_at = _now_mono
                    _ppt_file = ppt_state.get("presentation", "")
                    _ppt_slide = _coerce_slide_number(ppt_state.get("slide"))
                    _now_hhmm = datetime.now().strftime("%H:%M")
                    _now_hhmmss = datetime.now().strftime("%H:%M:%S")
                    _entry = next(
                        (e for e in slides_log if e["file"] == _ppt_file and e["slide"] == _ppt_slide and e["first_seen_hhmm"] == _now_hhmm),
                        None,
                    )
                    if _entry:
                        _entry["seconds_spent"] += _PPT_TRACK_INTERVAL
                        log.info("ppt", f"Slide +{_PPT_TRACK_INTERVAL:.0f}s: {Path(_ppt_file).stem} #{_ppt_slide} (total: {_entry['seconds_spent']}s)")
                    else:
                        slides_log.append({
                            "file": _ppt_file,
                            "slide": _ppt_slide,
                            "first_seen_at": _now_hhmmss,
                            "first_seen_hhmm": _now_hhmm,
                            "seconds_spent": _PPT_TRACK_INTERVAL,
                        })

                # ── Probe IntelliJ every 5 seconds and track git repos ──
                _now_mono = time.monotonic()
                if _now_mono - last_intellij_probe_at >= _INTELLIJ_PROBE_INTERVAL:
                    last_intellij_probe_at = _now_mono
                    try:
                        _ij = _platform.probe_intellij()
                        if _ij and _ij.get("frontmost", True):
                            _repo_entry = next(
                                (e for e in git_repos if e["path"] == _ij["path"] and e["branch"] == _ij["branch"]),
                                None,
                            )
                            if _repo_entry:
                                _repo_entry["seconds_spent"] += _INTELLIJ_PROBE_INTERVAL
                                log.info("intellij", f"Git +{_INTELLIJ_PROBE_INTERVAL:.0f}s: {_ij['project']} @ {_ij['branch']} (total: {_repo_entry['seconds_spent']:.0f}s)")
                            else:
                                git_repos.append({
                                    "project": _ij["project"],
                                    "path": _ij["path"],
                                    "branch": _ij["branch"],
                                    "seconds_spent": _INTELLIJ_PROBE_INTERVAL,
                                })
                    except Exception as _e:
                        log.error("intellij", f"Probe failed: {_e}")

                # ── Send activity_log to server when counts change ──
                _activity_key = (len(slides_log), len(git_repos))
                if _activity_key != _last_activity_log_key and ws_client.connected:
                    _last_activity_log_key = _activity_key
                    ws_client.send({"type": "activity_log", "slides_log": slides_log, "git_repos": git_repos})

                # ── Check for session management requests ──
                try:
                    session_req = _pending_requests.pop("session_request", None)
                    action = session_req.get("action") if session_req else None
                    global_state_persisted = False
                    if action == "create":
                        name = session_req["name"]
                        sid = session_req.get("session_id")
                        if sid:
                            set_current_session_id(sid)
                            _active_session_id = sid
                        folder = sessions_root / name
                        existed = folder.exists()
                        folder.mkdir(parents=True, exist_ok=True)
                        log.info("session", f"{'Found' if existed else 'Created'} folder: {folder}")
                        if not session_stack:
                            new_session = {
                                "name": name,
                                "started_at": datetime.now().isoformat(),
                                "ended_at": None,
                            }
                            session_stack.append(new_session)
                            current_key_points, summary_watermark = load_key_points(folder)
                            _do_save_daemon_state()
                            global_state_persisted = True
                            notes_file = find_notes_in_folder(folder)
                            config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                            sync_session_to_server(config, session_stack, current_key_points, slides_log=slides_log, git_repos=git_repos)
                            transcript_state.reset()
                            # try:  # disabled — no longer using Audio Hijack
                            #     _sync_audiohijack_language(config)
                            # except Exception:
                            #     pass
                        _push_session_folders()
                        participant_join_link = (
                            f"{config.server_url}/{_active_session_id}"
                            if _active_session_id
                            else f"{config.server_url}/"
                        )
                        log.info(
                            "session",
                            f"Session started: {name} (stack size: {len(session_stack)}) | participant join: {participant_join_link}",
                        )

                    elif action == "start":
                        name = session_req["name"]
                        folder = sessions_root / name
                        folder.mkdir(parents=True, exist_ok=True)
                        # Pause the current session while the nested one is active
                        if session_stack:
                            pause_session(session_stack[-1], datetime.now(), reason="nested")
                        new_session = {
                            "name": name,
                            "started_at": datetime.now().isoformat(),
                            "ended_at": None,
                        }
                        session_stack.append(new_session)
                        current_key_points, summary_watermark = load_key_points(folder)
                        _do_save_daemon_state()
                        global_state_persisted = True
                        notes_file = find_notes_in_folder(folder)
                        config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                        sync_session_to_server(config, session_stack, current_key_points, slides_log=slides_log, git_repos=git_repos)
                        transcript_state.reset()
                        slides_log = []
                        git_repos = []
                        _last_activity_log_key = (0, 0)
                        # try:  # disabled — no longer using Audio Hijack
                        #     _sync_audiohijack_language(config)
                        # except Exception:
                        #     pass
                        log.info("session", f"Started: {name}")

                    elif action == "end" and session_stack:
                        ended = session_stack.pop()
                        ended["ended_at"] = datetime.now().isoformat()
                        ended_folder = sessions_root / ended["name"]
                        # Save the current session's full state snapshot before clearing
                        _latest_session_snapshot = _pending_requests.pop("session_snapshot_result", None)
                        if _latest_session_snapshot and ended_folder.exists():
                            try:
                                save_session_state(ended_folder, _latest_session_snapshot)
                                log.info("session", f"Saved final snapshot for {ended['name']}")
                            except Exception as e:
                                log.error("session", f"Failed to save final snapshot: {e}")
                        save_key_points(ended_folder, current_key_points, summary_watermark, session_start_date(ended))
                        parent_snapshot = None
                        if session_stack:
                            # Nested session ended — restore parent
                            parent = session_stack[-1]
                            resume_session(parent, datetime.now())
                            parent_folder = sessions_root / parent["name"]
                            current_key_points, summary_watermark = load_key_points(parent_folder)
                            notes_file = find_notes_in_folder(parent_folder)
                            config = dc_replace(config, session_folder=parent_folder, session_notes=notes_file)
                            # Load saved activity state from parent session snapshot
                            parent_ss_path = parent_folder / "session_state.json"
                            if parent_ss_path.exists():
                                try:
                                    parent_snapshot = json.loads(parent_ss_path.read_text(encoding="utf-8"))
                                    log.info("session", f"Loaded parent snapshot from {parent_ss_path}")
                                except Exception as e:
                                    log.error("session", f"Failed to load parent snapshot: {e}")
                            log.info("session", f"Ended: {ended['name']}, restored: {parent['name']}")
                        else:
                            # Main session ended — clear everything
                            current_key_points = []
                            summary_watermark = 0
                            config = dc_replace(config, session_folder=None, session_notes=None)
                            slides_log = []
                            git_repos = []
                            _last_activity_log_key = (0, 0)
                            _active_session_id = None
                            log.info("session", f"Ended: {ended['name']}")
                        _do_save_daemon_state()
                        global_state_persisted = True
                        sync_session_to_server(
                            config, session_stack, current_key_points,
                            session_state=parent_snapshot,
                            slides_log=slides_log, git_repos=git_repos,
                        )
                        transcript_state.reset()

                    elif action == "rename":
                        new_name = session_req["name"]
                        if session_stack:
                            old_name = session_stack[-1]["name"]
                            new_folder = sessions_root / new_name
                            # Load existing points from new folder FIRST (before overwriting)
                            existing_pts, existing_wm = load_key_points(new_folder) if new_folder.exists() else ([], 0)
                            new_folder.mkdir(parents=True, exist_ok=True)
                            if existing_pts:
                                current_key_points, summary_watermark = existing_pts, existing_wm
                            else:
                                save_key_points(new_folder, current_key_points, summary_watermark, session_start_date(session_stack[-1]))
                            session_stack[-1]["name"] = new_name
                            _do_save_daemon_state()
                            global_state_persisted = True
                            notes_file = find_notes_in_folder(new_folder)
                            config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                            sync_session_to_server(config, session_stack, current_key_points, slides_log=slides_log, git_repos=git_repos)
                            log.info("session", f"Renamed: {old_name} → {new_name}")

                    elif action == "pause" and session_stack:
                        pause_session(session_stack[-1], datetime.now(), reason="explicit")
                        _do_save_daemon_state()
                        global_state_persisted = True
                        sync_session_to_server(config, session_stack, current_key_points, slides_log=slides_log, git_repos=git_repos)
                        log.info("session", f"Paused: {session_stack[-1]['name']}")

                    elif action == "resume" and session_stack:
                        resume_session(session_stack[-1], datetime.now())
                        _do_save_daemon_state()
                        global_state_persisted = True
                        sync_session_to_server(config, session_stack, current_key_points, slides_log=slides_log, git_repos=git_repos)
                        transcript_state.reset()
                        log.info("session", f"Resumed: {session_stack[-1]['name']}")

                    elif action == "create_talk_folder":
                        _now = datetime.now()
                        talk_name = f"{_now.strftime('%Y-%m-%d %H:%M')} talk"
                        talk_folder = sessions_root / talk_name
                        talk_folder.mkdir(parents=True, exist_ok=True)

                        # Push talk onto stack without disconnecting participants
                        session_stack.append({
                            "name": talk_name,
                            "started_at": _now.isoformat(),
                            "status": "active",
                        })
                        talk_points, talk_wm = load_key_points(talk_folder)
                        current_key_points, summary_watermark = talk_points, talk_wm
                        _do_save_daemon_state()
                        global_state_persisted = True
                        notes_file = find_notes_in_folder(talk_folder)
                        config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                        # Sync to server without disconnecting participants (no "action" key)
                        sync_session_to_server(
                            config, session_stack, talk_points,
                            discussion_points=talk_points,
                            slides_log=slides_log,
                            git_repos=git_repos,
                        )
                        log.info("session", f"Created talk folder: {talk_name}")
                    if action:
                        _send_global_state_saved_ack(ws_client, session_req, action, global_state_persisted, _active_session_id)

                except Exception as e:
                    log.error("session", f"Request error: {e}")

                # ── Re-detect session folder on date change or if notes not yet found (every 5s) ──
                today = date.today()
                # Audio Hijack restart guard — disabled (no longer using Audio Hijack)
                # if now - last_raw_transcript_guard_check_at >= _RAW_TRANSCRIPT_GUARD_INTERVAL:
                #     last_raw_transcript_guard_check_at = now
                #     if last_hijack_restart_for_missing_today != today:
                #         try:
                #             if _should_restart_for_missing_today_raw(config.folder, today):
                #                 log.info(
                #                     "transcript",
                #                     f"No raw transcript file for today ({today.isoformat()}); only yesterday exists. "
                #                     "Restarting Audio Hijack and sleeping 3s to force today's file.",
                #                 )
                #                 _platform.restart_audiohijack()
                #                 time.sleep(3)
                #                 log.info("transcript", "Audio Hijack restart guard completed (slept 3s)")
                #                 last_hijack_restart_for_missing_today = today
                #         except Exception as e:
                #             log.error("transcript", f"Audio Hijack restart guard failed: {e}")

                config, last_detected_date, last_session_check_at, _session_status_pending = (
                    _refresh_session_folder_binding(
                        config=config,
                        sessions_root=sessions_root,
                        session_stack=session_stack,
                        today=today,
                        last_detected_date=last_detected_date,
                        last_session_check_at=last_session_check_at,
                        now_mono=now,
                    )
                )

                sf_name = config.session_folder.name if config.session_folder else None
                sn_name = config.session_notes.name if config.session_notes else None

                # ── Sync AudioHijack language once per day — disabled ──
                # if last_lang_sync_date != today:
                #     try:
                #         _sync_audiohijack_language(config)
                #         last_lang_sync_date = today
                #     except Exception as e:
                #         log.error("daemon", f"Failed to sync AudioHijack language: {e}")

                # ── Auto-update + server connectivity check via /api/status ──
                try:
                    status_data = _get_json(f"{config.server_url}/api/status")
                    if server_disconnected:
                        log.info("daemon", "Reconnected to server.")
                        server_disconnected = False
                        _session_status_pending = True

                    # Auto-update: exit if server version changed
                    if _startup_version:
                        current_version = status_data.get("backend_version")
                        if current_version and current_version != _startup_version:
                            log.info("daemon", f"Server version changed: {_startup_version} → {current_version}")
                            log.info("daemon", "Exiting for auto-update (exit code 42)...")
                            _LOCK_FILE.unlink(missing_ok=True)
                            sys.exit(EXIT_CODE_UPDATE)

                    # Restore state if server lost it (e.g. after Railway redeploy)
                    if status_data.get("needs_restore"):
                        if _BACKUP_FILE.exists():
                            log.info("daemon", "Server needs state restore — sending backup via WS...")
                            backup_data = json.loads(_BACKUP_FILE.read_text(encoding="utf-8"))
                            if ws_client.send({"type": "state_restore", **backup_data}):
                                log.info("daemon", "State restore sent via WS")
                            else:
                                log.error("daemon", "State restore failed — WS not connected (will retry)")
                        else:
                            log.error("daemon", "Server needs state restore but no backup file found")
                except RuntimeError:
                    if not server_disconnected:
                        log.error("daemon", "Server unreachable (status check)")
                        server_disconnected = True

                # ── Push session info when changed, on reconnect, or periodically ──
                current_slides = load_slides_manifest(config.session_folder)
                current_slides_hash = hashlib.sha256(
                    json.dumps(current_slides, sort_keys=True).encode("utf-8")
                ).hexdigest()
                slides_changed = current_slides_hash != last_slides_payload_hash

                if _session_status_pending or slides_changed:
                    post_status("ready", "Agent ready.", config,
                                session_folder=sf_name, session_notes=sn_name, slides=current_slides)
                    last_slides_payload_hash = current_slides_hash

                # Push notes content when file is new or modified
                if config.session_notes:
                    try:
                        current_mtime = config.session_notes.stat().st_mtime
                    except OSError:
                        current_mtime = 0.0
                    notes_changed = current_mtime != last_notes_mtime and current_mtime > 0
                    if notes_changed:
                        notes_text = read_session_notes(config)
                        if notes_text:
                            ws_client.send({"type": "notes_content", "content": notes_text})
                            last_notes_mtime = current_mtime

                # ── Check for new quiz generation request (via WS) ──
                quiz_data = _pending_requests.pop("quiz_request", None)
                if quiz_data:
                    req = quiz_data.get("request")
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

                # ── Check for refine request (via WS) ──
                refine_data = _pending_requests.pop("quiz_refine", None)
                if refine_data:
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

                # ── Check for debate AI cleanup request (via WS) ──
                debate_data = _pending_requests.pop("debate_ai_request", None)
                if debate_data:
                    debate_req = debate_data.get("request")
                    if debate_req:
                        log.info("daemon", f"Debate AI cleanup requested: '{debate_req['statement'][:60]}'")
                        try:
                            result = run_debate_ai_cleanup(debate_req, config.api_key, config.model)
                            ws_client.send({"type": "debate_ai_result", **result})
                            n_new = len(result.get("new_arguments", []))
                            n_merges = len(result.get("merges", []))
                            log.info("daemon", f"Debate AI done: {n_merges} merges, {n_new} new args")
                        except Exception as e:
                            log.error("daemon", f"Debate AI cleanup failed: {e}")
                            # Post empty result so backend advances to prep anyway
                            ws_client.send({
                                "type": "debate_ai_result",
                                "merges": [], "cleaned": [], "new_arguments": [],
                            })

                # ── Transcription language change via WS — disabled (no longer using Audio Hijack) ──
                # lang_data = _pending_requests.pop("transcription_language_request", None)
                # if lang_data:
                #     lang_req = lang_data.get("language")
                #     if lang_req:
                #         log.info("daemon", f"Transcription language change requested: {lang_req}")
                #         try:
                #             _platform.set_audiohijack_language(lang_req)
                #             ws_client.send({
                #                 "type": "transcription_language_status",
                #                 "language": lang_req,
                #             })
                #             log.info("daemon", f"AudioHijack language set to: {lang_req}")
                #         except Exception as e:
                #             log.error("daemon", f"Failed to set AudioHijack language: {e}")

                # ── Email participant feedback ──
                try:
                    feedback_data = _get_json(
                        f"{config.server_url}/api/feedback/pending",
                        config.host_username, config.host_password,
                    )
                    for text in feedback_data.get("items", []):
                        log.info("email", f"Feedback received: {text[:80]}")
                        email_notify("💬 Workshop feedback", text)
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
                            if max_ts >= 86400:
                                # Elapsed-style VTT timestamp exceeds 24 h — use current wall-clock time
                                latest_time = datetime.now().strftime("%H:%M:%S")
                            else:
                                h, rem = divmod(int(max_ts), 3600)
                                m, s = divmod(rem, 60)
                                latest_time = f"{h:02d}:{m:02d}:{s:02d}"
                        else:
                            line_count = 0
                            latest_time = None
                        if line_count != last_transcript_line_count:
                            last_transcript_line_count = line_count
                        ws_client.send({
                            "type": "transcript_status",
                            "line_count": line_count,
                            "total_lines": total_lines,
                            "latest_ts": latest_time,
                        })
                    except SystemExit:
                        pass
                    except Exception as e:
                        log.error("transcript", f"Error: {e}")

                    # ── Push token usage alongside transcript stats ──
                    try:
                        ws_client.send({"type": "token_usage", **get_usage().to_dict()})
                    except Exception as e:
                        log.error("daemon", f"Token usage push failed: {e}")

                # ── Process state snapshot result (pushed by backend every 7s) ──
                snapshot_result = _pending_requests.pop("state_snapshot_result", None)
                if snapshot_result:
                    try:
                        snapshot_json = json.dumps(snapshot_result, sort_keys=True)
                        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
                        if snapshot_hash != last_snapshot_hash:
                            _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                            tmp_file = _BACKUP_FILE.with_suffix(".tmp")
                            tmp_file.write_text(snapshot_json, encoding="utf-8")
                            os.rename(str(tmp_file), str(_BACKUP_FILE))
                            last_snapshot_hash = snapshot_hash
                            s = snapshot_result.get("state", snapshot_result)
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
                            backup_log = f"State backup: {', '.join(parts)}"
                            if backup_log != last_state_backup_log:
                                log.info("daemon", backup_log)
                                last_state_backup_log = backup_log
                    except Exception as e:
                        log.error("daemon", f"State snapshot save failed: {e}")

                # ── Check for full-reset / forced summary request (via WS) ──
                full_reset_data = _pending_requests.pop("summary_full_reset", None)
                if full_reset_data:
                    log.info("summarizer", "Full reset — triggering regeneration")

                force_data = _pending_requests.pop("summary_force", None)
                force_summary = bool(force_data) or bool(full_reset_data)

                # ── On-demand summary generation (incremental when possible) ──
                if force_summary and session_stack:
                    current_key_points, summary_watermark = run_summary_cycle(
                        config, session_stack, sessions_root,
                        current_key_points, summary_watermark,
                    )

                # ── Process session snapshot result (pushed by backend every 7s) ──
                session_snapshot = _pending_requests.pop("session_snapshot_result", None)
                if session_snapshot:
                    snapshot_sid = session_snapshot.get("session_id")
                    if isinstance(snapshot_sid, str) and snapshot_sid:
                        if snapshot_sid != _active_session_id:
                            _active_session_id = snapshot_sid
                            _do_save_daemon_state()
                    current_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
                    if current_folder and current_folder.exists():
                        try:
                            save_session_state(current_folder, session_snapshot)
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
    finally:
        ws_client.stop()


if __name__ == "__main__":
    run()
