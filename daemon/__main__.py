"""Host Daemon — main orchestrator.

Run as: python3 -m daemon
"""

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import replace as dc_replace
from datetime import date, datetime
from pathlib import Path

from daemon import log
from daemon.config import (
    DAEMON_POLL_INTERVAL,
    DEFAULT_TRANSCRIPT_MINUTES,
    config_from_env,
    find_session_folder,
)
from daemon.lock import (
    _HEARTBEAT_INTERVAL,
    _LOCK_FILE,
    check_and_acquire_lock,
    install_signal_handlers,
    write_lock,
)
from daemon.quiz.history import auto_generate, auto_generate_topic, auto_refine
from daemon.quiz.poll_api import post_status
from daemon.session import pending as session_pending
from daemon.session import state as session_shared_state
from daemon.session_state import (
    GLOBAL_STATE_FILENAME,
    SESSION_STATE_FILENAME,
    daemon_state_to_stack,
    find_notes_in_folder,
    find_session_folder_by_id,
    load_daemon_state,
    load_session_meta,
    load_session_state,
    load_slides_manifest,
    pause_session,
    resolve_materials_folder,
    resume_session,
    save_daemon_state,
    save_session_meta,
    save_session_state,
    session_meta_to_stack,
    session_start_date,
    session_state_path,
    set_current_session_id,
    sync_session_to_server,
)
from daemon.slides.loop import SlidesRunner
from daemon.summary.loop import (
    get_ai_summary_mtime,
    get_ai_summary_raw,
    load_key_points,
    run_summary_cycle,
    save_key_points,
)
from daemon.transcript.loader import load_transcription_files
from daemon.transcript.state import TranscriptStateManager
from daemon.upload import handle_file_ready_for_download as _handle_file_download
from daemon.ws_client import DaemonWsClient

# ── PowerPoint helpers ─────────────────────────────────────────────────────────

_PPT_UNMAPPED_PRESENTATIONS_ALERTED: set[str] = set()


def _read_session_id_from_session_folder(folder: Path) -> str | None:
    path = session_state_path(folder)
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


def _state_hash(snapshot: dict | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    payload = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _flush_session_state_backup(
    *,
    sessions_root: Path,
    session_stack: list[dict],
    session_snapshot: dict | None,
    last_flushed_hash: str | None,
    force: bool = False,
) -> tuple[str | None, bool]:
    """Persist active session snapshot if changed (or forced)."""
    if not session_stack or not isinstance(session_snapshot, dict):
        return last_flushed_hash, False
    folder_name = session_stack[-1].get("name")
    if not folder_name:
        return last_flushed_hash, False
    target_folder = sessions_root / folder_name
    current_hash = _state_hash(session_snapshot)
    if current_hash is None:
        return last_flushed_hash, False
    if not force and current_hash == last_flushed_hash:
        return last_flushed_hash, False
    try:
        save_session_state(target_folder, session_snapshot)
        return current_hash, True
    except Exception as e:
        log.error("session", f"Failed to persist {SESSION_STATE_FILENAME}: {e}")
        return last_flushed_hash, False


def _ensure_session_state_file_for_resume(
    *,
    session_folder: Path,
    session_snapshot: dict | None,
) -> bool:
    """Create/populate session-state.json on resume if missing or empty."""
    state_file = session_state_path(session_folder)
    missing_or_empty = (not state_file.exists()) or state_file.stat().st_size == 0
    if not missing_or_empty:
        return False
    seed_snapshot = session_snapshot if isinstance(session_snapshot, dict) else {}
    save_session_state(session_folder, seed_snapshot)
    return True


def _flush_global_state_backup(
    *,
    sessions_root: Path,
    global_state: dict | None,
    last_flushed_hash: str | None,
    force: bool = False,
) -> tuple[str | None, bool]:
    if not isinstance(global_state, dict):
        return last_flushed_hash, False
    current_hash = _state_hash(global_state)
    if current_hash is None:
        return last_flushed_hash, False
    if not force and current_hash == last_flushed_hash:
        return last_flushed_hash, False
    try:
        save_daemon_state(sessions_root, global_state)
        return current_hash, True
    except Exception as e:
        log.error("session", f"Failed to persist {GLOBAL_STATE_FILENAME}: {e}")
        return last_flushed_hash, False


def _build_runtime_session_snapshot(
    *,
    active_session_id: str | None,
    session_stack: list[dict],
) -> dict:
    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.misc.state import misc_state
    from daemon.participant.state import participant_state
    from daemon.poll.state import poll_state
    from daemon.qa.state import qa_state
    from daemon.wordcloud.state import wordcloud_state

    qa_payload: dict[str, dict] = {}
    for qid, q in qa_state.questions.items():
        qa_payload[qid] = {
            "id": q.get("id", qid),
            "text": q.get("text", ""),
            "author": q.get("author", ""),
            "upvoters": sorted(list(q.get("upvoters", set()))),
            "answered": bool(q.get("answered", False)),
            "timestamp": q.get("timestamp"),
        }

    debate_snapshot = debate_state.snapshot()
    poll_timer_started_at = (
        poll_state.poll_timer_started_at.isoformat()
        if poll_state.poll_timer_started_at
        else None
    )
    poll_opened_at = (
        poll_state.poll_opened_at.isoformat()
        if poll_state.poll_opened_at
        else None
    )
    session_name = session_stack[-1]["name"] if session_stack else None

    participants_payload: dict[str, dict[str, object]] = {}
    participant_ids = set(participant_state.participant_names)
    participant_ids |= set(participant_state.participant_avatars)
    participant_ids |= set(participant_state.scores)
    participant_ids |= set(participant_state.locations)
    participant_ids |= set(participant_state.location_timezones)
    participant_ids |= set(participant_state.location_countries)
    for pid in participant_ids:
        row: dict[str, object] = {}
        if pid in participant_state.participant_names:
            row["name"] = participant_state.participant_names[pid]
        if pid in participant_state.participant_avatars:
            row["avatar"] = participant_state.participant_avatars[pid]
        if pid in participant_state.scores:
            row["score"] = participant_state.scores[pid]
        if pid in participant_state.locations:
            row["location"] = participant_state.locations[pid]
        if pid in participant_state.location_timezones:
            row["location_tz"] = participant_state.location_timezones[pid]
        if pid in participant_state.location_countries:
            row["location_country"] = participant_state.location_countries[pid]
        if pid in participant_state.online_participants:
            row["online"] = True
        participants_payload[pid] = row

    return {
        "session_name": session_name,
        "mode": participant_state.mode,
        "current_activity": participant_state.current_activity,
        "participants": participants_payload,
        "poll": {
            "definition": poll_state.poll,
            "active": poll_state.poll_active,
            "correct_ids": poll_state.poll_correct_ids,
            "opened_at": poll_opened_at,
            "timer_seconds": poll_state.poll_timer_seconds,
            "timer_started_at": poll_timer_started_at,
            "votes": dict(poll_state.votes),
        },
        "qa_questions": qa_payload,
        "wordcloud": {
            "words": dict(wordcloud_state.words),
            "word_order": list(wordcloud_state.word_order),
            "topic": wordcloud_state.topic,
        },
        "codereview": {
            "snippet": codereview_state.snippet,
            "language": codereview_state.language,
            "phase": codereview_state.phase,
            "selections": {
                pid: sorted(list(lines)) for pid, lines in codereview_state.selections.items()
            },
            "confirmed": sorted(list(codereview_state.confirmed)),
        },
        "debate": {
            "statement": debate_snapshot.get("statement"),
            "phase": debate_snapshot.get("phase"),
            "sides": dict(debate_snapshot.get("sides", {})),
            "arguments": list(debate_snapshot.get("arguments", [])),
            "champions": dict(debate_snapshot.get("champions", {})),
            "auto_assigned": list(debate_snapshot.get("auto_assigned", [])),
            "first_side": debate_snapshot.get("first_side"),
            "round_index": debate_snapshot.get("round_index"),
            "round_timer_seconds": debate_snapshot.get("round_timer_seconds"),
            "round_timer_started_at": debate_snapshot.get("round_timer_started_at"),
        },
        "slides_current": misc_state.slides_current,
    }


def _without_session_id(snapshot: dict | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    if "session_id" not in snapshot:
        return dict(snapshot)
    out = dict(snapshot)
    out.pop("session_id", None)
    return out


def _apply_runtime_snapshot_restore(snapshot: dict | None) -> None:
    """Apply a persisted session snapshot to in-memory daemon state caches."""
    if not isinstance(snapshot, dict) or not snapshot:
        return

    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.misc.state import misc_state
    from daemon.participant.state import participant_state
    from daemon.qa.state import qa_state
    from daemon.wordcloud.state import wordcloud_state

    participant_state.sync_from_restore(snapshot)
    _schedule_backfill_location_metadata()
    wordcloud_state.sync_from_restore(snapshot)
    qa_state.sync_from_restore(snapshot)
    misc_state.sync_from_restore(snapshot)
    codereview_state.sync_from_restore(snapshot)
    debate_state.sync_from_restore(snapshot)


def _schedule_backfill_location_metadata() -> None:
    """Schedule best-effort async backfill for snapshots missing location_tz/location_country/city."""
    from daemon.slides.router import get_event_loop as _get_event_loop

    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_backfill_participant_location_metadata(), loop)


async def _backfill_participant_location_metadata() -> None:
    """Best-effort backfill for legacy snapshots missing location_tz/location_country/city."""
    from daemon.participant.router import _COORDS_RE, _resolve_location_metadata
    from daemon.participant.state import participant_state

    ps = participant_state
    for pid, raw_loc in list(ps.locations.items()):
        loc = str(raw_loc or "").strip()
        if not loc:
            continue
        already_resolved = ps.location_timezones.get(pid) and ps.location_countries.get(pid)
        is_raw_coords = bool(_COORDS_RE.match(loc))
        if already_resolved and not is_raw_coords:
            continue
        try:
            tz, country, city = await _resolve_location_metadata(loc)
        except Exception:
            continue
        if city:
            ps.locations[pid] = city
        if tz:
            ps.location_timezones[pid] = tz
        if country:
            ps.location_countries[pid] = country


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
    """Resolve a PowerPoint deck name to a slide slug and download URL.

    Uses misc_state.slides_catalog first (has runtime UUID slugs), then
    falls back to the JSON catalog file. This ensures the slug matches
    what participants see in their catalog.
    """
    from daemon.misc.state import misc_state

    normalized_name = _normalize_slide_match_key(presentation_name)
    server_base = server_url.rstrip("/")

    # Primary: match against misc_state.slides_catalog (runtime, has correct UUID slugs)
    for slug, entry in misc_state.slides_catalog.items():
        if not isinstance(entry, dict):
            continue
        aliases = {
            str(entry.get("title") or "").strip(),
            str(entry.get("name") or "").strip(),
        }
        normalized_aliases = {_normalize_slide_match_key(a) for a in aliases if a}
        if normalized_name and normalized_name in normalized_aliases:
            return {
                "slug": slug,
                "url": f"{server_base}/api/slides/download/{slug}",
                "matched": True,
            }

    # Fallback: match against catalog JSON file (for entries not yet in misc_state)
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
                        "url": f"{server_base}/api/slides/download/{slug}",
                        "target_pdf": target_pdf,
                        "matched": True,
                    }
        except Exception as e:
            log.error("ppt", f"Failed reading slides catalog map: {e}")

    fallback_slug = _slugify(Path(presentation_name).stem)
    return {
        "slug": fallback_slug,
        "url": f"{server_base}/api/slides/download/{fallback_slug}",
        "target_pdf": f"{Path(presentation_name).stem}.pdf",
        "matched": False,
    }


def _send_global_state_saved_ack(
    ws_client,
    session_req: dict | None,
    action: str | None,
    session_id: str | None,
) -> None:
    pass  # global_state_saved removed: Railway no longer tracks ACKs


def _broadcast_notes_summary_counts(probe: dict) -> None:
    """Broadcast notes and summary line counts to participants and host via WS."""
    from daemon.ws_messages import NotesUpdatedMsg, SummaryUpdatedMsg
    from daemon.ws_publish import broadcast
    broadcast(NotesUpdatedMsg(count=probe["notes_non_empty_lines"]))
    broadcast(SummaryUpdatedMsg(count=probe["summary_point_count"]))



def _read_non_empty_line_count(path: Path | None) -> int:
    if path is None or not path.exists() or not path.is_file():
        return 0
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in content.splitlines() if line.strip())


def _file_mtime_ns(path: Path | None) -> int | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _build_notes_summary_probe(session_folder: Path | None) -> dict:
    from daemon.misc.content_files import _parse_summary_points
    notes_file = find_notes_in_folder(session_folder) if session_folder else None
    summary_file = (session_folder / "ai-summary.md") if session_folder else None
    if summary_file and not summary_file.exists():
        summary_file = None
    summary_raw: str | None = None
    if summary_file:
        try:
            summary_raw = summary_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            summary_raw = None
    return {
        "session_folder": str(session_folder) if session_folder else None,
        "notes_file": str(notes_file) if notes_file else None,
        "notes_mtime_ns": _file_mtime_ns(notes_file),
        "notes_non_empty_lines": _read_non_empty_line_count(notes_file),
        "summary_file": str(summary_file) if summary_file else None,
        "summary_mtime_ns": _file_mtime_ns(summary_file),
        "summary_point_count": len(_parse_summary_points(summary_raw)),
    }


def _probe_change_parts(previous: dict | None, current: dict) -> str:
    if previous is None:
        return "initial"
    parts: list[str] = []
    if previous.get("session_folder") != current.get("session_folder"):
        parts.append("session")
    notes_changed = (
        previous.get("notes_file") != current.get("notes_file")
        or previous.get("notes_mtime_ns") != current.get("notes_mtime_ns")
        or previous.get("notes_non_empty_lines") != current.get("notes_non_empty_lines")
    )
    summary_changed = (
        previous.get("summary_file") != current.get("summary_file")
        or previous.get("summary_mtime_ns") != current.get("summary_mtime_ns")
        or previous.get("summary_point_count") != current.get("summary_point_count")
    )
    if notes_changed:
        parts.append("notes")
    if summary_changed:
        parts.append("summary")
    return ",".join(parts) if parts else "none"


def _log_notes_summary_probe(reason: str, probe: dict, change_parts: str | None = None) -> None:
    session_label = probe.get("session_folder") or "<none>"
    notes_label = Path(probe["notes_file"]).name if probe.get("notes_file") else "MISSING"
    summary_label = Path(probe["summary_file"]).name if probe.get("summary_file") else "MISSING"
    suffix = f" changed={change_parts}" if change_parts else ""
    log.info(
        "notes-summary",
        f"{reason}:{suffix} session={session_label} "
        f"notes_file={notes_label} notes_non_empty_lines={probe['notes_non_empty_lines']} "
        f"summary_file={summary_label} summary_point_count={probe['summary_point_count']}",
    )


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
        log.info("session", f"Session: {resolved_folder.name}")
        if resolved_notes:
            notes_lines = len(resolved_notes.read_text(encoding="utf-8", errors="replace").splitlines())
            log.info("session", f"Notes found ({notes_lines} lines): {resolved_notes.name}")
        else:
            log.info("session", "Notes file: NOT FOUND")
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
            if source != "stack":
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
    _boot_sessions_root = _sessions_root_from_env()
    _boot_state = load_daemon_state(_boot_sessions_root)
    _boot_level = str(_boot_state.get("log_level") or "").strip().lower()
    if _boot_level in {"info", "debug"}:
        log.set_level(_boot_level)
        log.info("daemon", f"Restored persisted log level: {_boot_level}")
    log.info("daemon", f"🚀 Starting — connecting to {config.server_url}")

    # ── Initialize WebSocket client for backend communication ──
    ws_client = DaemonWsClient()
    _pending_requests: dict[str, dict] = {}  # msg_type → data, populated by WS handlers, consumed by main loop

    def _ws_handler(msg_type: str):
        def handler(data):
            _pending_requests[msg_type] = data
        return handler

    # quiz_request and quiz_refine are now served via daemon REST endpoints (daemon/quiz/router.py)
    # and stored in daemon.quiz.pending — no longer via WS push from Railway
    # debate_ai_request handled directly by debate router (no longer via WS polling)
    ws_client.register_handler("summary_force", _ws_handler("summary_force"))
    ws_client.register_handler("summary_full_reset", _ws_handler("summary_full_reset"))
    # session_request is now served via daemon REST endpoint (daemon/session/router.py)
    # stored in daemon.session.pending — no longer via WS push from Railway
    ws_client.register_handler("sync_files", _ws_handler("sync_files"))

    from daemon.proxy_handler import handle_proxy_request
    ws_client.register_handler("proxy_request",
        lambda data: handle_proxy_request(data, ws_client),
        inline=True)

    # Set ws_client on modules that send results back via WS
    from daemon import ws_publish
    ws_publish.set_ws_client(ws_client)

    from daemon.session_state import set_ws_client as set_session_ws
    set_session_ws(ws_client)

    from daemon.scores import scores as daemon_scores
    from daemon.session.router import set_ws_client as set_session_router_ws
    set_session_router_ws(ws_client)

    def _handle_scores_reset(data):
        daemon_scores.reset()
        from daemon.ws_messages import ScoresUpdatedMsg
        ws_publish.broadcast(ScoresUpdatedMsg(scores=daemon_scores.snapshot()))

    ws_client.register_handler("scores_reset", _handle_scores_reset)

    # NOTE: pdf_download_complete WS handler removed — /check now uses REST
    # POST /api/slides/download-from-gdrive/{slug} on Railway instead.

    ws_client.register_handler(
        "file_ready_for_download",
        lambda data: _handle_file_download(data, config),
    )

    def _push_host_participant_list() -> None:
        try:
            import asyncio as _asyncio

            from daemon.host_state_router import _build_host_participants_list
            from daemon.slides.router import get_event_loop as _get_event_loop
            from daemon.ws_messages import ParticipantListUpdatedMsg
            from daemon.ws_publish import notify_host as _notify_host

            _loop = _get_event_loop()
            if _loop and _loop.is_running():
                _asyncio.run_coroutine_threadsafe(
                    _notify_host(
                        ParticipantListUpdatedMsg(
                            participants=_build_host_participants_list(),
                        )
                    ),
                    _loop,
                )
        except Exception:
            pass

    def _broadcast_active_count(ps) -> None:
        """Broadcast active (online named) participant count to Railway so participants see it."""
        try:
            from daemon.ws_messages import ActiveParticipantsCountUpdatedMsg
            from daemon.ws_publish import broadcast as _broadcast
            count = len([p for p in ps.online_participants
                         if not p.startswith("__") and p in ps.participant_names])
            _broadcast(ActiveParticipantsCountUpdatedMsg(count=count))
        except Exception:
            pass

    def _handle_participant_presence(data: dict) -> None:
        from daemon.participant.state import participant_state as _participant_state

        pid = str(data.get("uuid", "")).strip()
        if not pid or pid.startswith("__"):
            return

        if bool(data.get("online")):
            _participant_state.online_participants.add(pid)
        else:
            _participant_state.online_participants.discard(pid)
        _push_host_participant_list()
        _broadcast_active_count(_participant_state)

    ws_client.register_handler("participant_presence", _handle_participant_presence)

    # State push handler — daemon receives current state from Railway on connect
    from daemon.misc.state import misc_state

    def _handle_daemon_state_push(data):
        _apply_runtime_snapshot_restore(data)
        if "online_participants" in data:
            from daemon.participant.state import participant_state as _ps
            _push_host_participant_list()
            _broadcast_active_count(_ps)

    ws_client.register_handler("daemon_state_push", _handle_daemon_state_push)

    if config.project_folder:
        log.info("daemon", f"Project folder configured: {config.project_folder}")
        if not os.path.isdir(config.project_folder):
            log.error("daemon", f"PROJECT_FOLDER does not exist: {config.project_folder}")
    else:
        pass  # PROJECT_FOLDER is optional

    # Start background material indexer
    materials_folder = resolve_materials_folder()
    if materials_folder is not None:
        from daemon.rag.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        raw = os.environ.get("MATERIALS_FOLDER", "").strip() or "<auto-detect>"
        log.error("daemon", f"MATERIALS_FOLDER not found (MATERIALS_FOLDER={raw}) — indexer disabled")

    # ── Session stack initialization (early — needed for transcript log) ──
    sessions_root = _boot_sessions_root
    log.info("session", f"Sessions root: {sessions_root}")
    session_shared_state.set_sessions_root(sessions_root)
    _raw_state = _boot_state
    _active_session_id: str | None = None
    session_stack: list[dict] = []

    if "main" in _raw_state or "stack" in _raw_state:
        # Old format — migrate in-memory to stack and continue with new global-state flow
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
        log.info("session", "Migrated old daemon state format")
    elif "active_session_id" in _raw_state:
        # New format — find folder by session_id, load metadata from session-state.json
        _active_session_id = _raw_state.get("active_session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                _meta = load_session_meta(_active_folder)
                session_stack = session_meta_to_stack(_meta, _active_folder.name)
                if not session_stack:
                    session_stack = [{
                        "name": _active_folder.name,
                        "started_at": datetime.now().isoformat(),
                        "ended_at": None,
                    }]

    config, _ = _bind_initial_session_folder(config, sessions_root, session_stack)
    current_key_points: list[dict] = []
    summary_watermark: int = 0

    pending_global_state: dict | None = None

    def _build_global_state() -> dict:
        state = {"log_level": log.get_level()}
        if _active_session_id:
            state["active_session_id"] = _active_session_id
        return state

    def _do_save_daemon_state():
        """Queue global-state.json write and persist session metadata immediately."""
        nonlocal pending_global_state
        nonlocal _active_session_id
        pending_global_state = _build_global_state()
        # Keep shared session state up to date for the daemon REST router
        session_shared_state.set_active_session(_active_session_id, session_stack)

    def _persist_log_level(level: str) -> None:
        _do_save_daemon_state()
        log.info("daemon", f"Queued log level persist in {GLOBAL_STATE_FILENAME}: {level}")

    import daemon.host_server as _host_server_mod
    _host_server_mod.set_log_level_persist_callback(_persist_log_level)

    def _resolve_gdrive_url(session_folder) -> str | None:
        """Resolve Google Drive web URL for a session folder."""
        try:
            import sys as _sys
            import os as _os
            _scripts_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if _scripts_dir not in _sys.path:
                _sys.path.insert(0, _scripts_dir)
            from scripts.resolve_gdrive_link import resolve_gdrive_url as _resolve_fn
            return _resolve_fn(str(session_folder))
        except Exception as e:
            log.error("session", f"Failed to resolve Google Drive link: {e}")
            return None

    if session_stack:
        # Restore from persisted stack
        current_folder = config.session_folder or (sessions_root / session_stack[-1]["name"])
        current_key_points, summary_watermark = load_key_points(current_folder)
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
        }]
        current_key_points, summary_watermark = load_key_points(config.session_folder)
        _do_save_daemon_state()
    # Resolve Google Drive folder URL for the active session folder
    if config.session_folder:
        _gdrive_url = _resolve_gdrive_url(config.session_folder)
        if _gdrive_url:
            misc_state.gdrive_url = _gdrive_url
            log.info("session", f"Google Drive: {_gdrive_url}")
    # Publish initial session state to daemon REST router
    session_shared_state.set_active_session(_active_session_id, session_stack)
    slides_runner = SlidesRunner(config)
    slides_runner.start()

    # ── Addon bridge client (connects to wispr-flow WS server at localhost:8765) ──
    from daemon.addon_bridge_client import AddonBridgeClient
    from daemon.addon_bridge_client import set_client as _set_bridge_client
    _bridge = AddonBridgeClient()
    _set_bridge_client(_bridge)

    # Set up connection callback to send session state on reconnect
    def _on_addon_connection_change(connected: bool) -> None:
        if connected:
            # Addons just connected — check if there's an active session
            from daemon.session import state as session_state
            active_id = session_state.get_active_session_id()
            if active_id:
                participant_join_link = f"{config.server_url}/{active_id}"
                log.info("addons   ", f"→ active session {participant_join_link}")
                from daemon import addon_bridge_client
                addon_bridge_client.send_session_started(participant_join_link)

    _bridge.set_on_connection_change(_on_addon_connection_change)
    _bridge.start()

    # Session state: the transcript text used to generate the current preview
    last_text: str | None = None
    last_quiz: dict | None = None
    last_detected_date: date | None = None
    last_heartbeat_at = 0.0
    last_session_check_at = 0.0
    last_transcript_stats_at = 0.0
    last_transcript_line_count = -1
    last_slides_payload_hash: str | None = None
    last_slides_mtime_scan_at = 0.0

    _prev_overlay_connected: bool = False
    # Sync initial state to server — include session-state.json if present in the active folder
    startup_session_state: dict = {}
    try:
        if session_stack:
            startup_session_state = load_session_state(sessions_root / session_stack[-1]["name"])
            if startup_session_state:
                log.info("session", f"Loaded {SESSION_STATE_FILENAME} for restore ({len(startup_session_state)} keys)")
                _apply_runtime_snapshot_restore(startup_session_state)
        _startup_folder = (config.session_folder or (sessions_root / session_stack[-1]["name"])) if session_stack else None
        sync_session_to_server(
            config,
            session_stack,
            current_key_points,
            startup_session_state if startup_session_state else None,
            session_id=_active_session_id,
            file_time=get_ai_summary_mtime(_startup_folder) if _startup_folder else None,
            raw_markdown=get_ai_summary_raw(_startup_folder) if _startup_folder else None,
        )
    except Exception as e:
        log.error("session", f"Initial sync failed: {e}")

    notes_summary_probe_prev: dict | None = _build_notes_summary_probe(config.session_folder)
    runtime_session_snapshot: dict | None = _without_session_id(startup_session_state) if startup_session_state else None
    last_persist_poll_at: float = 0.0
    last_session_state_hash: str | None = _state_hash(runtime_session_snapshot)
    last_global_state_hash: str | None = None
    transcript_state = TranscriptStateManager()
    # Session folders push removed — host.js does not handle session_folders messages

    # ── Git code timestamp ──
    import subprocess as _subprocess
    def _get_git_commit_timestamp() -> str | None:
        try:
            result = _subprocess.run(
                ["git", "log", "-1", "--format=%aI"],
                capture_output=True, text=True, timeout=5,
                cwd=Path(__file__).resolve().parent.parent,
            )
            ts = result.stdout.strip()
            return ts if ts else None
        except Exception:
            return None

    _code_timestamp: str | None = _get_git_commit_timestamp()
    if _code_timestamp:
        log.info("daemon", f"Code timestamp: {_code_timestamp}")
    import daemon.host_server as _host_server_mod
    _host_server_mod.code_timestamp = _code_timestamp

    def _push_code_timestamp():
        if _code_timestamp:
            ws_client.send({"type": "code_timestamp", "timestamp": _code_timestamp})

    ws_client.on_connect(_push_code_timestamp)

    # Re-sync active session state to backend on every (re)connect (e.g. after backend restart)
    def _sync_session_on_reconnect():
        if not session_stack:
            return
        reconnect_session_state = runtime_session_snapshot if runtime_session_snapshot else None
        try:
            _reconnect_folder = sessions_root / session_stack[-1]["name"] if session_stack else None
            sync_session_to_server(config, session_stack, current_key_points, reconnect_session_state, session_id=_active_session_id, file_time=get_ai_summary_mtime(_reconnect_folder) if _reconnect_folder else None, raw_markdown=get_ai_summary_raw(_reconnect_folder) if _reconnect_folder else None)
            log.info("session", f"Sent active session to backend: '{session_stack[-1]['name']}'")
        except Exception as e:
            log.error("session", f"Session re-sync on reconnect failed: {e}")
        _broadcast_notes_summary_counts(notes_summary_probe_prev)
    ws_client.on_connect(_sync_session_on_reconnect)

    # Re-probe Railway slide cache on every (re)connect (e.g. after Railway redeploy)
    ws_client.on_connect(slides_runner.probe_railway_cache)

    ws_client.start()

    # ── Start local host panel server ──
    from daemon.config import DAEMON_HOST_PORT
    from daemon.host_server import start_host_server
    start_host_server(config.server_url, port=DAEMON_HOST_PORT)
    log.info("daemon", f"Host panel: http://127.0.0.1:{DAEMON_HOST_PORT}/host")

    try:
        while True:
            if not ws_client.connected:
                time.sleep(DAEMON_POLL_INTERVAL)
                continue

            # ── Drain pending WS messages (handlers run on main thread) ──
            ws_client.drain_queue()

            # ── Process slide events from addon bridge ──
            for _slide_event in _bridge.drain_slides():
                _deck = _slide_event.get("deck")
                _slide_num = _slide_event.get("slide")
                if _deck and _slide_num:
                    if slides_runner and slides_runner._slides_config:
                        catalog_file = getattr(slides_runner._slides_config, "catalog_file", None)
                        _target = _resolve_presentation_slide_target(
                            presentation_name=_deck,
                            server_url=config.server_url,
                            catalog_file=catalog_file,
                        )
                        if _target and _target.get("matched", True):
                            _sc = {
                                "url": _target["url"],
                                "slug": _target["slug"],
                                "source_file": _deck,
                                "presentation_name": _deck,
                                "current_page": _slide_num,
                            }
                            if misc_state.slides_current != _sc:
                                misc_state.slides_current = _sc
                                from daemon.ws_messages import SlidesCurrentMsg
                                ws_publish.broadcast(SlidesCurrentMsg(slides_current=_sc))
                                log.info("addons   ", f"← Slide: {_deck}:{_slide_num}")
                        elif _target and not _target.get("matched", True):
                            if misc_state.slides_current is not None:
                                misc_state.slides_current = None
                                from daemon.ws_messages import SlidesCurrentMsg
                                ws_publish.broadcast(SlidesCurrentMsg(slides_current=None))
                    else:
                        _sc = {"presentation_name": _deck, "current_page": _slide_num}
                        if misc_state.slides_current != _sc:
                            misc_state.slides_current = _sc
                            from daemon.ws_messages import SlidesCurrentMsg
                            ws_publish.broadcast(SlidesCurrentMsg(slides_current=_sc))

            # ── Push overlay_connected state change to host ──
            _curr_overlay = _bridge.connected
            if _curr_overlay != _prev_overlay_connected:
                _prev_overlay_connected = _curr_overlay
                try:
                    import asyncio as _asyncio

                    from daemon.slides.router import get_event_loop as _get_event_loop
                    _loop = _get_event_loop()
                    if _loop and _loop.is_running():
                        from daemon.ws_messages import OverlayConnectedMsg
                        from daemon.ws_publish import notify_host as _notify_host
                        _asyncio.run_coroutine_threadsafe(
                            _notify_host(OverlayConnectedMsg(overlay_connected=_curr_overlay)),
                            _loop,
                        )
                except Exception:
                    pass

            # ── Heartbeat: update lock file so other instances know we're alive ──
            try:
                now = time.monotonic()
                if now - last_heartbeat_at >= _HEARTBEAT_INTERVAL:
                    write_lock()
                    last_heartbeat_at = now

                # ── Read git activity from file ──
                # ── Check for session management requests ──
                try:
                    session_req = session_pending.pop("session_request")
                    action = session_req.get("action") if session_req else None
                    if action == "create":
                        name = session_req["name"]
                        sid = session_req.get("session_id")
                        session_type = session_req.get("type", "workshop")
                        did_sync_in_create = False
                        if sid:
                            set_current_session_id(sid)
                            _active_session_id = sid
                        folder = sessions_root / name
                        existed = folder.exists()
                        folder.mkdir(parents=True, exist_ok=True)
                        if sid:
                            save_session_meta(folder, {"session_id": sid})
                        log.info("session", f"{'Found' if existed else 'Created'} folder: {folder}")
                        if existed:
                            try:
                                if _ensure_session_state_file_for_resume(
                                    session_folder=folder,
                                    session_snapshot=runtime_session_snapshot,
                                ):
                                    last_session_state_hash = _state_hash(
                                        runtime_session_snapshot if isinstance(runtime_session_snapshot, dict) else {}
                                    )
                                    log.info("session", f"Self-healed missing/empty {SESSION_STATE_FILENAME} for create")
                            except Exception as e:
                                log.error("session", f"Failed self-healing {SESSION_STATE_FILENAME}: {e}")
                        if not session_stack:
                            # Fresh main session: clear runtime caches so participants/avatars/
                            # count and activity artifacts don't leak from previous sessions.
                            from daemon.codereview.state import (
                                codereview_state as _codereview_state,
                            )
                            from daemon.debate.state import debate_state as _debate_state
                            from daemon.leaderboard.state import (
                                leaderboard_state as _leaderboard_state,
                            )
                            from daemon.misc.state import misc_state as _misc_state
                            from daemon.participant.state import (
                                participant_state as _participant_state,
                            )
                            from daemon.poll.state import poll_state as _poll_state
                            from daemon.qa.state import qa_state as _qa_state
                            from daemon.scores import scores as _scores_state
                            from daemon.wordcloud.state import wordcloud_state as _wordcloud_state

                            _participant_state.reset(mode="conference" if session_type == "talk" else "workshop")
                            _wordcloud_state.clear()
                            _qa_state.clear()
                            _misc_state.reset_for_new_session()
                            _poll_state.clear()
                            _codereview_state.clear()
                            _debate_state.reset()
                            _leaderboard_state.reset()
                            _scores_state.reset()
                            restore_snapshot = _without_session_id(load_session_state(folder))
                            runtime_session_snapshot = restore_snapshot
                            _apply_runtime_snapshot_restore(restore_snapshot)
                            last_session_state_hash = _state_hash(runtime_session_snapshot)

                            new_session = {
                                "name": name,
                                "started_at": datetime.now().isoformat(),
                                "ended_at": None,
                            }
                            session_stack.append(new_session)
                            current_key_points, summary_watermark = load_key_points(folder)
                            _do_save_daemon_state()
                            notes_file = find_notes_in_folder(folder)
                            if notes_file:
                                notes_lines = len(notes_file.read_text(encoding="utf-8", errors="replace").splitlines())
                                log.info("session", f"Notes found ({notes_lines} lines): {notes_file.name}")
                            config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                            sync_session_to_server(
                                config,
                                session_stack,
                                current_key_points,
                                session_state=runtime_session_snapshot if runtime_session_snapshot else None,
                                session_id=_active_session_id,
                                file_time=get_ai_summary_mtime(folder),
                                raw_markdown=get_ai_summary_raw(folder),
                            )
                            did_sync_in_create = True
                            # mode_changed removed — host.js/participant.js don't handle it; mode is in full state on reconnect
                            transcript_state.reset()
                        if not did_sync_in_create:
                            # Resume may arrive when a session stack is already in memory
                            # (e.g. after daemon restart with stale stack restore). Ensure
                            # active session id is persisted/broadcast even in that path.
                            _do_save_daemon_state()
                            sync_session_to_server(
                                config,
                                session_stack,
                                current_key_points,
                                session_state=runtime_session_snapshot if runtime_session_snapshot else None,
                                session_id=_active_session_id,
                                file_time=get_ai_summary_mtime(folder),
                                raw_markdown=get_ai_summary_raw(folder),
                            )
                        participant_join_link = (
                            f"{config.server_url}/{_active_session_id}"
                            if _active_session_id
                            else f"{config.server_url}/"
                        )
                        # Notify addons of session start
                        from daemon import addon_bridge_client
                        addon_bridge_client.send_session_started(participant_join_link)
                        log.info("addons   ", f"→ started session {participant_join_link}")
                        log.info(
                            "session",
                            f"Session: {name}",
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
                        notes_file = find_notes_in_folder(folder)
                        if notes_file:
                            notes_lines = len(notes_file.read_text(encoding="utf-8", errors="replace").splitlines())
                            log.info("session", f"Notes found ({notes_lines} lines): {notes_file.name}")
                        config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                        sync_session_to_server(config, session_stack, current_key_points, file_time=get_ai_summary_mtime(folder), raw_markdown=get_ai_summary_raw(folder))
                        transcript_state.reset()
                        log.info("session", f"Session: {name}")

                    elif action == "end" and session_stack:
                        runtime_session_snapshot = _build_runtime_session_snapshot(
                            active_session_id=_active_session_id,
                            session_stack=session_stack,
                        )
                        last_session_state_hash, wrote = _flush_session_state_backup(
                            sessions_root=sessions_root,
                            session_stack=session_stack,
                            session_snapshot=runtime_session_snapshot,
                            last_flushed_hash=last_session_state_hash,
                            force=True,
                        )
                        if wrote and session_stack:
                            log.info("session", f"Forced flush {SESSION_STATE_FILENAME} for {session_stack[-1]['name']}")
                        ended = session_stack.pop()
                        ended["ended_at"] = datetime.now().isoformat()
                        ended_folder = sessions_root / ended["name"]
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
                            parent_snapshot = _without_session_id(load_session_state(parent_folder))
                            if parent_snapshot:
                                runtime_session_snapshot = parent_snapshot
                                _apply_runtime_snapshot_restore(parent_snapshot)
                                last_session_state_hash = _state_hash(parent_snapshot)
                                log.info("session", f"Loaded parent snapshot from {session_state_path(parent_folder)}")
                            # Notify addons: parent session resumed (send session_started)
                            participant_join_link = (
                                f"{config.server_url}/{_active_session_id}"
                                if _active_session_id
                                else f"{config.server_url}/"
                            )
                            from daemon import addon_bridge_client
                            addon_bridge_client.send_session_started(participant_join_link)
                            log.info("addons   ", f"→ started session {participant_join_link}")
                            log.info("session", f"Ended: {ended['name']}, restored: {parent['name']}")
                        else:
                            # Main session ended — clear everything
                            current_key_points = []
                            summary_watermark = 0
                            config = dc_replace(config, session_folder=None, session_notes=None)
                            _active_session_id = None
                            # Notify addons that session ended
                            from daemon import addon_bridge_client
                            addon_bridge_client.send_session_ended()
                            log.info("session", f"Ended: {ended['name']}")
                        _do_save_daemon_state()
                        if pending_global_state is None:
                            pending_global_state = _build_global_state()
                        last_global_state_hash, _ = _flush_global_state_backup(
                            sessions_root=sessions_root,
                            global_state=pending_global_state,
                            last_flushed_hash=last_global_state_hash,
                            force=True,
                        )
                        sync_session_to_server(
                            config, session_stack, current_key_points,
                            session_state=parent_snapshot,
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
                            notes_file = find_notes_in_folder(new_folder)
                            config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                            sync_session_to_server(config, session_stack, current_key_points)
                            log.info("session", f"Renamed: {old_name} → {new_name}")

                    elif action == "pause" and session_stack:
                        pause_session(session_stack[-1], datetime.now(), reason="explicit")
                        _do_save_daemon_state()
                        sync_session_to_server(config, session_stack, current_key_points)
                        log.info("session", f"Paused: {session_stack[-1]['name']}")

                    elif action == "resume" and session_stack:
                        resume_session(session_stack[-1], datetime.now())
                        _do_save_daemon_state()
                        resume_folder = sessions_root / session_stack[-1]["name"]
                        try:
                            if _ensure_session_state_file_for_resume(
                                session_folder=resume_folder,
                                session_snapshot=runtime_session_snapshot,
                            ):
                                last_session_state_hash = _state_hash(
                                    runtime_session_snapshot if isinstance(runtime_session_snapshot, dict) else {}
                                )
                                log.info("session", f"Self-healed missing/empty {SESSION_STATE_FILENAME} for resume")
                        except Exception as e:
                            log.error("session", f"Failed self-healing {SESSION_STATE_FILENAME}: {e}")
                        sync_session_to_server(config, session_stack, current_key_points)
                        transcript_state.reset()
                        # Notify addons of session resume
                        participant_join_link = (
                            f"{config.server_url}/{_active_session_id}"
                            if _active_session_id
                            else f"{config.server_url}/"
                        )
                        from daemon import addon_bridge_client
                        addon_bridge_client.send_session_started(participant_join_link)
                        log.info("addons   ", f"→ started session {participant_join_link}")
                        log.info("session", f"Session: {session_stack[-1]['name']}")

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
                        notes_file = find_notes_in_folder(talk_folder)
                        config = dc_replace(config, session_folder=talk_folder, session_notes=notes_file)

                        # Sync to server without disconnecting participants (no "action" key)
                        sync_session_to_server(
                            config, session_stack, talk_points,
                            discussion_points=talk_points,
                        )
                        log.info("session", f"Created talk folder: {talk_name}")
                    if action:
                        _send_global_state_saved_ack(ws_client, session_req, action, _active_session_id)

                except Exception as e:
                    log.error("session", f"Request error: {e}")

                # ── Re-detect session folder on date change or if notes not yet found (every 5s) ──
                today = date.today()
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
                notes_summary_probe = _build_notes_summary_probe(config.session_folder)
                if notes_summary_probe_prev != notes_summary_probe:
                    _log_notes_summary_probe(
                        "change-detected",
                        notes_summary_probe,
                        _probe_change_parts(notes_summary_probe_prev, notes_summary_probe),
                    )
                    notes_summary_probe_prev = notes_summary_probe
                    _broadcast_notes_summary_counts(notes_summary_probe)

                if now - last_persist_poll_at >= 3.0:
                    last_persist_poll_at = now
                    if session_stack:
                        runtime_session_snapshot = _build_runtime_session_snapshot(
                            active_session_id=_active_session_id,
                            session_stack=session_stack,
                        )
                    if pending_global_state is None:
                        pending_global_state = _build_global_state()
                    last_global_state_hash, _ = _flush_global_state_backup(
                        sessions_root=sessions_root,
                        global_state=pending_global_state,
                        last_flushed_hash=last_global_state_hash,
                        force=False,
                    )
                    last_session_state_hash, wrote = _flush_session_state_backup(
                        sessions_root=sessions_root,
                        session_stack=session_stack,
                        session_snapshot=runtime_session_snapshot,
                        last_flushed_hash=last_session_state_hash,
                        force=False,
                    )


                sf_name = config.session_folder.name if config.session_folder else None
                sn_name = config.session_notes.name if config.session_notes else None

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

                # notes_content send removed: notes are no longer pushed via WS

                # ── Check for new quiz generation request (via daemon REST endpoint) ──
                from daemon.quiz.pending import pop as _quiz_pending_pop
                quiz_data = _quiz_pending_pop("quiz_request")
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

                # ── Check for refine request (via daemon REST endpoint) ──
                refine_data = _quiz_pending_pop("quiz_refine")
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

                # ── Scan PPTX mtimes every 10s — detect slide updates quickly ──
                if slides_runner and now - last_slides_mtime_scan_at >= 10.0:
                    last_slides_mtime_scan_at = now
                    if slides_runner.scan_pptx_mtimes():
                        from daemon.slides.router import _broadcast_slides_cache_status
                        _broadcast_slides_cache_status()

                # ── Push transcript stats every 10s ──
                if now - last_transcript_stats_at >= 10.0:
                    last_transcript_stats_at = now
                    try:
                        entries = load_transcription_files(config.folder)
                        timed = [(ts, txt) for ts, txt in entries if ts is not None]
                        if timed:
                            max_ts = max(ts for ts, _ in timed)
                            cutoff = max_ts - DEFAULT_TRANSCRIPT_MINUTES * 60
                            recent = [(ts, txt) for ts, txt in timed if ts >= cutoff and txt.strip()]
                            line_count = len(recent)
                        else:
                            line_count = 0
                        if line_count != last_transcript_line_count:
                            last_transcript_line_count = line_count
                        # transcript_status and token_usage sends removed — host.js does not handle them
                        pass
                    except SystemExit:
                        pass
                    except Exception as e:
                        log.error("transcript", f"Error: {e}")

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

                # ── Static file sync (triggered by backend on WS connect) ──
                sync_files_data = _pending_requests.pop("sync_files", None)
                if sync_files_data is not None:
                    from daemon.static_sync import sync_static_files
                    static_dir = Path(__file__).resolve().parent.parent / "static"
                    remote_hashes = sync_files_data.get("static_hashes", {})
                    changed_files = sync_static_files(
                        static_dir, remote_hashes,
                        config.server_url, config.host_username, config.host_password,
                    )
                    if changed_files:
                        changed = len(changed_files)
                        changed_names = ", ".join(changed_files)
                        ws_client.send({"type": "broadcast", "event": {"type": "reload"}})
                        log.info("static-sync", f"Triggered browser reload after sync {changed} file(s): {changed_names}")

            except RuntimeError as e:
                log.error("daemon", f"Error in main loop: {e}")
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
