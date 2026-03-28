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
from datetime import date, datetime
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
from daemon.transcript.loop import TranscriptTimestampAppender, TranscriptNormalizerRunner
from daemon.transcript.loader import load_transcription_files
from daemon.transcript.query import load_normalized_entries
from daemon.transcript.session import compute_active_windows, format_startup_log
from daemon.transcript.state import TranscriptStateManager
from daemon.slides.loop import SlidesPollingRunner
from daemon.materials.mirror import MaterialsMirrorRunner
from daemon.materials.ws_runner import SlidesOnDemandWsRunner
from daemon.ws_client import DaemonWsClient
from daemon.session_state import (
    resolve_materials_folder,
    check_daily_timing,
    load_daemon_state,
    daemon_state_to_stack,
    stack_to_daemon_state,
    save_daemon_state,
    pause_session,
    resume_session,
    session_start_date,
    save_session_state,
    find_notes_in_folder,
    sync_session_to_server,
    load_slides_manifest,
)
from daemon.lock import (
    check_and_acquire_lock,
    write_lock,
    install_signal_handlers,
    cleanup_lock,
    _LOCK_FILE,
    _HEARTBEAT_INTERVAL,
)

EXIT_CODE_UPDATE = 42  # signals start.sh to git pull and restart
_BACKUP_DIR = Path.home() / ".training-assistant"
_BACKUP_FILE = _BACKUP_DIR / "state-backup.json"

# ── PowerPoint helpers ─────────────────────────────────────────────────────────

_PPT_NO_APP = "__NO_PPT__"
_PPT_NO_PRESENTATION = "__NO_PRESENTATION__"
_PPT_SLIDE_UNKNOWN = "__SLIDE_UNKNOWN__"
_PPT_UNMAPPED_PRESENTATIONS_ALERTED: set[str] = set()
_PPT_APPLESCRIPT = """
if application "Microsoft PowerPoint" is not running then
    return "__NO_PPT__"
end if

tell application "Microsoft PowerPoint"
    if (count of presentations) is 0 then
        return "__NO_PRESENTATION__"
    end if

    set presentationName to name of active presentation
    set slideNumber to 1
    set isPresenting to "false"

    try
        if (count of slide show windows) > 0 then
            set isPresenting to "true"
            set slideNumber to current show position of slide show view of slide show window 1
        else
            try
                set slideNumber to slide index of slide of view of active window
            on error
                try
                    set slideNumber to slide index of slide of view of document window 1
                on error
                    set slideNumber to "__SLIDE_UNKNOWN__"
                end try
            end try
        end if
    on error
        set slideNumber to "__SLIDE_UNKNOWN__"
    end try

    return presentationName & tab & isPresenting & tab & (slideNumber as string)
end tell
""".strip()


_AUDIOHIJACK_SESSIONS_PLIST = os.path.expanduser(
    "~/Library/Application Support/Audio Hijack 4/Sessions.plist"
)


def _set_audiohijack_language(lang_code: str) -> None:
    """Kill AudioHijack, update TranscribeBlock languageCode in Sessions.plist, restart."""
    import plistlib
    import time as _time

    subprocess.run(["pkill", "-x", "Audio Hijack"], capture_output=True)
    _time.sleep(1.5)

    plist_path = _AUDIOHIJACK_SESSIONS_PLIST
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)
    changed = False
    for session_item in data.get("modelItems", []):
        for block in session_item.get("sessionData", {}).get("geBlocks", []):
            if block.get("geObjectInfo") == "TranscribeBlock":
                block.setdefault("geNodeProperties", {})["languageCode"] = lang_code
                changed = True
    if changed:
        with open(plist_path, "wb") as f:
            plistlib.dump(data, f)

    subprocess.Popen(["open", "-a", "Audio Hijack"])


def _coerce_slide_number(value) -> int:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "missing value" or raw == _PPT_SLIDE_UNKNOWN:
        return 1
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, number)


def _parse_powerpoint_probe_output(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text or text in {_PPT_NO_APP, _PPT_NO_PRESENTATION}:
        return None
    parts = text.split("\t")
    if len(parts) < 2:
        return None
    presentation = parts[0].strip()
    if not presentation:
        return None
    if len(parts) >= 3:
        is_presenting = parts[1].strip() == "true"
        slide_number = _coerce_slide_number(parts[2].strip())
    else:
        is_presenting = False
        slide_number = _coerce_slide_number(parts[1].strip())
    return {"presentation": presentation, "slide": slide_number, "presenting": is_presenting}


def _probe_powerpoint_state(timeout_seconds: float = 2.5) -> tuple[dict | None, str | None]:
    try:
        result = subprocess.run(
            ["osascript", "-e", _PPT_APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=max(0.1, timeout_seconds),
            check=False,
        )
    except FileNotFoundError:
        return None, "osascript not available on PATH"
    except subprocess.TimeoutExpired:
        return None, f"osascript timed out after {timeout_seconds:.1f}s"
    except Exception as e:
        return None, f"osascript failed: {e}"

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = f"osascript exit code {result.returncode}"
        return None, details

    return _parse_powerpoint_probe_output(result.stdout), None


def _beep_local() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", "beep"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        pass


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
            _beep_local()
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

    # Detect today's session folder
    sf, sn = find_session_folder(date.today())
    config = dc_replace(config, session_folder=sf, session_notes=sn)
    if sf:
        log.info("session", f"Session folder: {sf.name}")
        log.info("session", f"Notes file: {sn.name if sn else 'NOT FOUND'}")
    else:
        log.error("session", "No session folder found for today")

    # Start background material indexer
    materials_folder = resolve_materials_folder()
    if materials_folder is not None:
        from daemon.rag.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        raw = os.environ.get("MATERIALS_FOLDER", "").strip() or "<auto-detect>"
        log.error("daemon", f"MATERIALS_FOLDER not found (MATERIALS_FOLDER={raw}) — indexer disabled")

    # ── Session stack initialization (early — needed for transcript log) ──
    sessions_root = config.session_folder.parent if config.session_folder else Path.cwd()
    session_stack = daemon_state_to_stack(load_daemon_state(sessions_root))
    current_key_points: list[dict] = []
    summary_watermark: int = 0

    if session_stack:
        # Restore from persisted stack
        current_folder = sessions_root / session_stack[-1]["name"]
        current_key_points, summary_watermark = load_key_points(current_folder)
        log.info("session", f"Restored stack ({len(session_stack)} sessions), {len(current_key_points)} key points")
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
        }]
        current_key_points, summary_watermark = load_key_points(config.session_folder)
        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
        log.info("session", f"Auto-started: {config.session_folder.name}")

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

    timestamp_appender = TranscriptTimestampAppender(config.folder)
    timestamp_appender.start()
    transcript_normalizer = TranscriptNormalizerRunner(config.folder)
    transcript_normalizer.start()
    slides_runner = SlidesPollingRunner(config)
    slides_runner.start()
    materials_mirror = MaterialsMirrorRunner(config)
    materials_mirror.start()
    slides_on_demand_ws = SlidesOnDemandWsRunner(config)
    slides_on_demand_ws.start()
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
        sync_session_to_server(config, session_stack, current_key_points, startup_session_state)
    except Exception as e:
        log.error("session", f"Failed to sync initial state: {e}")

    last_summary_at = 0.0  # monotonic time of last summary run
    last_snapshot_hash: str | None = None  # hash of last saved state snapshot
    last_snapshot_check_at = 0.0  # monotonic time of last state-snapshot GET
    last_state_backup_log: str | None = None  # last emitted state-backup log line (dedupe consecutive repeats)
    transcript_state = TranscriptStateManager()
    _SAVE_INTERVAL = 5
    # Trigger immediate save on first iteration if a session is already active
    _save_counter = _SAVE_INTERVAL if session_stack else 0

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

                timestamp_appender.tick()
                transcript_normalizer.tick()
                slides_runner.tick()
                materials_mirror.tick()

                # ── Detect active PowerPoint presentation/slide via AppleScript ──
                ppt_state, ppt_error = _probe_powerpoint_state()
                if ppt_error:
                    if ppt_error != last_powerpoint_error:
                        log.error("ppt", f"AppleScript probe failed: {ppt_error}")
                        last_powerpoint_error = ppt_error
                else:
                    if last_powerpoint_error is not None:
                        log.info("ppt", "AppleScript probe recovered")
                        last_powerpoint_error = None
                    if ppt_state != last_powerpoint_state:
                        last_powerpoint_state = ppt_state
                        if ppt_state is None:
                            log.info("ppt", "No active PowerPoint presentation")
                        else:
                            ppt_stem = Path(ppt_state['presentation']).stem
                            raw_slide = _coerce_slide_number(ppt_state.get("slide"))
                            is_presenting = bool(ppt_state.get("presenting", False))
                            participant_page = max(1, raw_slide - 1) if is_presenting else raw_slide
                            fullscreen_flag = " [fullscreen]" if is_presenting else " [normal]"
                            log.info("ppt", f"📽️ Slide: {ppt_stem} : {raw_slide}{fullscreen_flag} → p.{participant_page} to participants")
                        try:
                            _sync_powerpoint_slide_to_server(config, slides_runner._slides_config, ppt_state, ws_client)
                        except Exception as e:
                            log.error("ppt", f"Failed to sync slides current to server: {e}")
                    else:
                        pass

                # ── Check for session management requests ──
                try:
                    session_req = _pending_requests.pop("session_request", None)
                    action = session_req.get("action") if session_req else None
                    if action == "start":
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
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        notes_file = find_notes_in_folder(folder)
                        config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                        sync_session_to_server(config, session_stack, current_key_points)
                        transcript_state.reset()
                        log.info("session", f"Started: {name}")

                    elif action == "end" and len(session_stack) > 1:
                        ended = session_stack.pop()
                        ended["ended_at"] = datetime.now().isoformat()
                        ended_folder = sessions_root / ended["name"]
                        save_key_points(ended_folder, current_key_points, summary_watermark, session_start_date(ended))
                        # Restore parent session and close its nested pause
                        parent = session_stack[-1]
                        resume_session(parent, datetime.now())
                        parent_folder = sessions_root / parent["name"]
                        current_key_points, summary_watermark = load_key_points(parent_folder)
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        notes_file = find_notes_in_folder(parent_folder)
                        config = dc_replace(config, session_folder=parent_folder, session_notes=notes_file)
                        sync_session_to_server(config, session_stack, current_key_points)
                        transcript_state.reset()
                        log.info("session", f"Ended: {ended['name']}, restored: {parent['name']}")

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
                            save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                            notes_file = find_notes_in_folder(new_folder)
                            config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                            sync_session_to_server(config, session_stack, current_key_points)
                            log.info("session", f"Renamed: {old_name} → {new_name}")

                    elif action == "pause" and session_stack:
                        pause_session(session_stack[-1], datetime.now(), reason="explicit")
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        sync_session_to_server(config, session_stack, current_key_points)
                        log.info("session", f"Paused: {session_stack[-1]['name']}")

                    elif action == "resume" and session_stack:
                        resume_session(session_stack[-1], datetime.now())
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        sync_session_to_server(config, session_stack, current_key_points)
                        transcript_state.reset()
                        log.info("session", f"Resumed: {session_stack[-1]['name']}")

                    elif action == "start_talk":
                        _now = datetime.now()
                        talk_name = f"{_now.strftime('%Y-%m-%d %H:%M')} talk"
                        talk_folder = sessions_root / talk_name
                        talk_folder.mkdir(parents=True, exist_ok=True)

                        # Save current (main) session state immediately before switching
                        # (request snapshot via WS — result will be saved when received)
                        current_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
                        if current_folder and current_folder.exists():
                            ws_client.send({"type": "session_snapshot_request"})

                        # Load talk's existing key points (if folder had prior data)
                        talk_points, talk_wm = load_key_points(talk_folder)

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
                            "started_at": _now.isoformat(),
                            "status": "active",
                        })
                        current_key_points, summary_watermark = talk_points, talk_wm
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        notes_file = find_notes_in_folder(talk_folder)
                        config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                        # Sync to server: mark current participants as paused, restore talk state
                        sync_session_to_server(
                            config, session_stack, talk_points,
                            session_state=talk_state,
                            discussion_points=talk_points,
                            action="start_talk",
                        )
                        transcript_state.reset()
                        log.info("session", f"START TALK: {talk_name}")

                    elif action == "end_talk":
                        if len(session_stack) < 2:
                            log.warning("daemon", "END TALK requested but no talk is active")
                        else:
                            # Save talk state before ending (request snapshot via WS — async save)
                            talk_folder = sessions_root / session_stack[-1]["name"]
                            if talk_folder.exists():
                                ws_client.send({"type": "session_snapshot_request"})
                                try:
                                    save_key_points(talk_folder, current_key_points, summary_watermark, session_start_date(session_stack[-1]))
                                except Exception as e:
                                    log.error("daemon", f"END TALK: failed to save key points: {e}")

                            # Pop talk, restore main
                            session_stack.pop()
                            save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))

                            main_folder = sessions_root / session_stack[0]["name"] if session_stack else None
                            current_key_points, summary_watermark = load_key_points(main_folder) if main_folder else ([], 0)

                            # Load main's saved session state for restore
                            main_state = None
                            if main_folder and (main_folder / "session_state.json").exists():
                                try:
                                    main_state = json.loads((main_folder / "session_state.json").read_text())
                                except Exception:
                                    pass

                            notes_file = find_notes_in_folder(main_folder) if main_folder else None
                            config = dc_replace(config, session_folder=main_folder, session_notes=notes_file)

                            # Sync to server: restore main participants, clear talk
                            sync_session_to_server(
                                config, session_stack, current_key_points,
                                session_state=main_state,
                                discussion_points=current_key_points,
                                action="end_talk",
                            )
                            transcript_state.reset()
                            log.info("daemon", f"END TALK: restored main session {session_stack[0]['name'] if session_stack else 'none'}")

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
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        notes_file = find_notes_in_folder(talk_folder)
                        config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                        # Sync to server without disconnecting participants (no "action" key)
                        sync_session_to_server(
                            config, session_stack, talk_points,
                            discussion_points=talk_points,
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
                    save_key_points(top_folder, current_key_points, summary_watermark, session_start_date(top))
                    # Pause all active sessions in the stack (day-end pause — not ended, resumes tomorrow)
                    for s in session_stack:
                        if s.get("ended_at") is None:
                            pause_session(s, now_wall, reason="day_end")
                    save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                    sync_session_to_server(config, session_stack, current_key_points)
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
                                resume_session(s, now_wall)
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        sync_session_to_server(config, session_stack, current_key_points)
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
                    current_key_points, summary_watermark = load_key_points(config.session_folder)
                    save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                    notes_file = find_notes_in_folder(config.session_folder)
                    config = dc_replace(config, session_notes=notes_file)
                    sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    log.info("session", f"Auto-started at 09:30: {config.session_folder.name}")

                # ── Daily timing events (5:30pm warning, 6pm auto-pause, midnight session end) ──
                if _timing_fired_date != today:
                    _timing_fired_date = today
                    _timing_fired_today = set()

                timing = check_daily_timing()
                if timing == "warning" and "warning" not in _timing_fired_today:
                    _timing_fired_today.add("warning")
                    try:
                        ws_client.send({
                            "type": "timing_event",
                            "event": "recording_warning",
                            "minutes_remaining": 30,
                        })
                        log.info("daemon", "Sent recording_warning event at 17:30")
                    except Exception as e:
                        log.error("daemon", f"Failed to send warning event: {e}")

                elif timing == "auto_pause" and "auto_pause" not in _timing_fired_today:
                    _timing_fired_today.add("auto_pause")
                    if session_stack and session_stack[-1].get("status") not in ("ended", "paused"):
                        try:
                            ws_client.send({"type": "session_request", "action": "pause"})
                            log.info("daemon", "Auto-paused recording at 18:00")
                        except Exception as e:
                            log.error("daemon", f"Failed to auto-pause: {e}")

                elif timing == "midnight" and "midnight" not in _timing_fired_today:
                    _timing_fired_today.add("midnight")
                    if session_stack:
                        session_stack[-1]["status"] = "ended"
                        save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
                        log.info("daemon", "Session marked as ended at midnight")

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
                            ws_client.send({"type": "state_restore", **backup_data})
                            log.info("daemon", "State restore sent via WS")
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

                # ── Check for transcription language change request (via WS) ──
                lang_data = _pending_requests.pop("transcription_language_request", None)
                if lang_data:
                    lang_req = lang_data.get("language")
                    if lang_req:
                        log.info("daemon", f"Transcription language change requested: {lang_req}")
                        try:
                            _set_audiohijack_language(lang_req)
                            ws_client.send({
                                "type": "transcription_language_status",
                                "language": lang_req,
                            })
                            log.info("daemon", f"AudioHijack language set to: {lang_req}")
                        except Exception as e:
                            log.error("daemon", f"Failed to set AudioHijack language: {e}")

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

                # ── Snapshot state for backup (every 7s) — request via WS ──
                if now - last_snapshot_check_at >= 7.0:
                    last_snapshot_check_at = now
                    ws_client.send({"type": "state_snapshot_request"})

                # ── Process state snapshot result (if received from backend) ──
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

                # ── Periodic session state snapshot save — request via WS ──
                _save_counter += 1
                if _save_counter >= _SAVE_INTERVAL:
                    _save_counter = 0
                    current_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
                    if current_folder and current_folder.exists():
                        ws_client.send({"type": "session_snapshot_request"})

                # ── Process session snapshot result (if received from backend) ──
                session_snapshot = _pending_requests.pop("session_snapshot_result", None)
                if session_snapshot:
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
        slides_on_demand_ws.stop()


if __name__ == "__main__":
    run()
