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
from datetime import date
from pathlib import Path

from daemon import log
from daemon.config import (
    DAEMON_POLL_INTERVAL,
    DEFAULT_TRANSCRIPT_MINUTES,
    Config,
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
from daemon.session import pending as session_pending
from daemon.session import state as session_shared_state
from daemon.session_state import (
    GLOBAL_STATE_FILENAME,
    SESSION_STATE_FILENAME,
    announce_session_cleared,
    announce_session_id,
    find_notes_in_folder,
    find_session_folder_by_id,
    load_daemon_state,
    load_session_state,
    load_slides_manifest,
    resolve_materials_folder,
    save_daemon_state,
    save_session_meta,
    save_session_state,
    session_state_path,
    set_current_session_id,
)
from daemon.slides.loop import SlidesRunner
from daemon.transcript.loader import load_transcription_files
from daemon.transcript.state import TranscriptStateManager
from daemon.upload import handle_file_ready_for_download as _handle_file_download
from daemon.ws_client import DaemonWsClient


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
    session_name: str | None,
    session_snapshot: dict | None,
    last_flushed_hash: str | None,
    force: bool = False,
) -> tuple[str | None, bool]:
    """Persist active session snapshot if changed (or forced)."""
    if not session_name or not isinstance(session_snapshot, dict):
        return last_flushed_hash, False
    target_folder = sessions_root / session_name
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
    session_name: str | None,
) -> dict:
    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.misc.state import misc_state
    from daemon.participant.state import participant_state
    from daemon.poll.state import poll_state
    from daemon.qa.state import qa_state
    from daemon.quiz.state import quiz_state
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
    quiz_timer_started_at = (
        quiz_state.quiz_timer_started_at.isoformat()
        if quiz_state.quiz_timer_started_at
        else None
    )
    quiz_opened_at = (
        quiz_state.quiz_opened_at.isoformat()
        if quiz_state.quiz_opened_at
        else None
    )
    participants_payload: dict[str, dict[str, object]] = {}
    participant_ids = set(participant_state.participant_names)
    participant_ids |= set(participant_state.participant_avatars)
    from daemon.scores import scores as daemon_scores
    participant_ids |= set(daemon_scores.scores)
    participant_ids |= set(participant_state.locations)
    participant_ids |= set(participant_state.location_timezones)
    participant_ids |= set(participant_state.location_countries)
    participant_ids |= set(participant_state.engagement)
    for pid in participant_ids:
        row: dict[str, object] = {}
        if pid in participant_state.participant_names:
            row["name"] = participant_state.participant_names[pid]
        if pid in participant_state.participant_avatars:
            row["avatar"] = participant_state.participant_avatars[pid]
        if pid in daemon_scores.scores:
            row["score"] = daemon_scores.scores[pid]
        if pid in participant_state.locations:
            row["location"] = participant_state.locations[pid]
        if pid in participant_state.location_timezones:
            row["location_tz"] = participant_state.location_timezones[pid]
        if pid in participant_state.location_countries:
            row["location_country"] = participant_state.location_countries[pid]
        if pid in participant_state.engagement:
            row["engagement"] = participant_state.engagement[pid]
        participants_payload[pid] = row

    return {
        "session_name": session_name,
        "mode": participant_state.mode,
        "current_activity": participant_state.current_activity,
        "participants": participants_payload,
        "quiz": {
            "definition": quiz_state.quiz,
            "active": quiz_state.quiz_active,
            "correct_indices": quiz_state.quiz_correct_indices or [],
            "opened_at": quiz_opened_at,
            "timer_seconds": quiz_state.quiz_timer_seconds,
            "timer_started_at": quiz_timer_started_at,
            "votes": dict(quiz_state.votes),
            "awarded_points": dict(quiz_state.awarded_points),
        },
        "poll": ({
            "data": poll_state.data.model_dump() if poll_state.data else None,
            "started": poll_state.started,
            "opened_at": poll_state.opened_at,
            "ended_at": poll_state.ended_at,
            "votes": dict(poll_state.votes),
            "host_extras": list(poll_state.host_extras),
        } if poll_state.data is not None or poll_state.votes else None),
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
        "current_slide": misc_state.current_slide,
        "slides_viewed": [dict(sv) for sv in misc_state.slides_viewed],
        "talk_presentation_name": misc_state.talk_presentation_name,
        "talk_presentation_url": misc_state.talk_presentation_url,
        "talk_presentation_slug": misc_state.talk_presentation_slug,
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

    from daemon.poll.state import PollData, poll_state
    poll_data = snapshot.get("poll")
    if poll_data:
        if poll_data.get("data"):
            poll_state.data = PollData.model_validate(poll_data["data"])
        poll_state.started = bool(poll_data.get("started", False))
        poll_state.opened_at = poll_data.get("opened_at")
        poll_state.ended_at = poll_data.get("ended_at")
        poll_state.votes = dict(poll_data.get("votes") or {})
        poll_state.host_extras = list(poll_data.get("host_extras") or [])
        poll_state.invalidate_counts()


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
    session_name: str | None,
    detected_folder: Path | None,
    detected_notes: Path | None,
) -> tuple[Path | None, Path | None, str]:
    """Resolve active session folder source: active session_name first, then today detection fallback."""
    if session_name:
        active_folder = sessions_root / session_name
        if active_folder.exists() and active_folder.is_dir():
            return active_folder, find_notes_in_folder(active_folder), "stack"
        log.error(
            "session",
            f"Active session folder missing on disk: {session_name}; fallback to today detection",
        )
    if detected_folder:
        return detected_folder, detected_notes, "today"
    return None, None, "none"





def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "slide"



def _normalize_slide_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", Path(str(value or "")).stem.lower())


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
            str(entry.get("source_name") or "").strip(),
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
                from daemon.slides.catalog import _title_to_pdf_name
                title = str(entry.get("title") or "").strip()
                target_pdf = _title_to_pdf_name(title) if title else f"{source.stem}.pdf"
                explicit_slug = str(entry.get("slug") or "").strip().lower()
                slug = explicit_slug or _slugify(Path(target_pdf).stem)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                aliases = {
                    source.name,
                    source.stem,
                    title,
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


def _broadcast_notes_summary_counts(probe: dict, change_parts: str) -> None:
    """Broadcast notes, summary, and/or agenda availability to participants via WS.

    Only broadcasts the message(s) for the part(s) that actually changed.
    Skips broadcasting when all session-content files are absent (e.g., fresh session
    start) — participants already get nulls/false from GET /api/participant/state.
    """
    notes_mtime_ns = probe.get("notes_mtime_ns")
    summary_mtime_ns = probe.get("summary_mtime_ns")
    agenda_mtime_ns = probe.get("agenda_mtime_ns")
    # Suppress only the very first ("initial") probe when nothing exists yet —
    # participants already get nulls/false from GET /api/participant/state. A later
    # present->absent transition is a real change and MUST broadcast so navs hide.
    if (
        change_parts == "initial"
        and notes_mtime_ns is None
        and summary_mtime_ns is None
        and agenda_mtime_ns is None
    ):
        return
    from datetime import datetime, timezone

    from daemon.ws_messages import AgendaUpdatedMsg, NotesUpdatedMsg, SummaryUpdatedMsg
    from daemon.ws_publish import broadcast
    parts = set(change_parts.split(","))
    if "notes" in parts or "session" in parts or "initial" in parts:
        notes_updated_at: str | None = None
        if notes_mtime_ns:
            notes_updated_at = datetime.fromtimestamp(notes_mtime_ns / 1e9, tz=timezone.utc).isoformat()
        broadcast(NotesUpdatedMsg(updated_at=notes_updated_at))
    if "summary" in parts or "session" in parts or "initial" in parts:
        summary_updated_at: str | None = None
        if summary_mtime_ns:
            summary_updated_at = datetime.fromtimestamp(summary_mtime_ns / 1e9, tz=timezone.utc).isoformat()
        broadcast(SummaryUpdatedMsg(updated_at=summary_updated_at))
    if "agenda" in parts or "session" in parts or "initial" in parts:
        broadcast(AgendaUpdatedMsg(has_agenda=agenda_mtime_ns is not None))



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
    agenda_file = _find_agenda_docx(session_folder)
    return {
        "session_folder": str(session_folder) if session_folder else None,
        "notes_file": str(notes_file) if notes_file else None,
        "notes_mtime_ns": _file_mtime_ns(notes_file),
        "notes_non_empty_lines": _read_non_empty_line_count(notes_file),
        "summary_file": str(summary_file) if summary_file else None,
        "summary_mtime_ns": _file_mtime_ns(summary_file),
        "summary_point_count": len(_parse_summary_points(summary_raw)),
        "agenda_file": str(agenda_file) if agenda_file else None,
        "agenda_mtime_ns": _file_mtime_ns(agenda_file),
    }


def _find_agenda_docx(session_folder: Path | None) -> Path | None:
    """Find a .docx agenda file in the session folder.
    Prefers 'agenda.docx', falls back to first .docx alphabetically."""
    if not session_folder or not session_folder.is_dir():
        return None
    docx_files = sorted(f for f in session_folder.iterdir()
                        if f.suffix.lower() == ".docx" and f.is_file())
    if not docx_files:
        return None
    for f in docx_files:
        if f.name.lower() == "agenda.docx":
            return f
    return docx_files[0]


def _agenda_path_from_probe(probe: dict) -> Path | None:
    """Resolve the agenda path captured by the session-content probe (or None)."""
    agenda_str = probe.get("agenda_file")
    return Path(agenda_str) if agenda_str else None


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
    agenda_changed = (
        previous.get("agenda_file") != current.get("agenda_file")
        or previous.get("agenda_mtime_ns") != current.get("agenda_mtime_ns")
    )
    if notes_changed:
        parts.append("notes")
    if summary_changed:
        parts.append("summary")
    if agenda_changed:
        parts.append("agenda")
    return ",".join(parts) if parts else "none"


def _log_notes_summary_probe(reason: str, probe: dict, change_parts: str | None = None) -> None:
    session_label = probe.get("session_folder") or "<none>"
    notes_label = Path(probe["notes_file"]).name if probe.get("notes_file") else "MISSING"
    summary_label = Path(probe["summary_file"]).name if probe.get("summary_file") else "MISSING"
    agenda_label = Path(probe["agenda_file"]).name if probe.get("agenda_file") else "MISSING"
    suffix = f" changed={change_parts}" if change_parts else ""
    log.info(
        "notes-summary",
        f"{reason}:{suffix} session={session_label} "
        f"notes_file={notes_label} notes_non_empty_lines={probe['notes_non_empty_lines']} "
        f"summary_file={summary_label} summary_point_count={probe['summary_point_count']} "
        f"agenda_file={agenda_label}",
    )


def _bind_initial_session_folder(config: Config, sessions_root: Path, session_name: str | None) -> tuple[Config, str]:
    """Resolve and log session folder binding at daemon startup."""
    today_folder = today_notes = None
    if not session_name:
        today_folder, today_notes = find_session_folder(date.today())
    resolved_folder, resolved_notes, resolved_source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_name=session_name,
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
    config: Config,
    sessions_root: Path,
    session_name: str | None,
    today: date,
    last_detected_date: date | None,
    last_session_check_at: float,
    now_mono: float,
) -> tuple[Config, date | None, float, bool]:
    """Periodic session-folder refresh: prefer active session_name, fallback to today detection when none."""
    notes_missing = config.session_notes is None
    date_changed = today != last_detected_date
    session_recheck_due = notes_missing and (now_mono - last_session_check_at >= 5.0)
    if not (date_changed or session_recheck_due):
        return config, last_detected_date, last_session_check_at, False

    last_session_check_at = now_mono
    detected_sf = detected_sn = None
    if not session_name:
        detected_sf, detected_sn = find_session_folder(today)

    sf, sn, source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_name=session_name,
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
    try:
        from daemon.telemetry import instrument_urllib, setup_tracing
        setup_tracing()
        instrument_urllib()
    except ImportError:
        pass

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

    from daemon.session.router import set_ws_client as set_session_router_ws
    set_session_router_ws(ws_client)

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
        from daemon.participant.router import _apply_browser_tz
        from daemon.participant.state import participant_state as _participant_state

        pid = str(data.get("uuid", "")).strip()
        if not pid or pid.startswith("__"):
            return

        if bool(data.get("online")):
            _participant_state.online_participants.add(pid)
            _apply_browser_tz(pid, data.get("tz"))
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
    session_name: str | None = None  # folder name of active session

    if "main" in _raw_state or "stack" in _raw_state:
        # Legacy format — extract session_id only, ignore stack
        _active_session_id = _raw_state.get("session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                session_name = _active_folder.name
        log.info("session", "Migrated old daemon state format")
    elif "active_session_id" in _raw_state:
        _active_session_id = _raw_state.get("active_session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                session_name = _active_folder.name

    config, _ = _bind_initial_session_folder(config, sessions_root, session_name)

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
        session_shared_state.set_active_session(_active_session_id, session_name)

    def _persist_log_level(level: str) -> None:
        _do_save_daemon_state()
        log.info("daemon", f"Queued log level persist in {GLOBAL_STATE_FILENAME}: {level}")

    import daemon.host_server as _host_server_mod
    _host_server_mod.set_log_level_persist_callback(_persist_log_level)

    def _resolve_gdrive_url(session_folder) -> str | None:
        """Resolve Google Drive web URL for a session folder."""
        try:
            import os as _os
            import sys as _sys
            _scripts_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if _scripts_dir not in _sys.path:
                _sys.path.insert(0, _scripts_dir)
            from scripts.resolve_gdrive_link import resolve_gdrive_url as _resolve_fn
            return _resolve_fn(str(session_folder))
        except Exception as e:
            log.error("session", f"Failed to resolve Google Drive link: {e}")
            return None

    if not session_name and config.session_folder:
        # Auto-start from today's detected session folder
        session_name = config.session_folder.name
        _do_save_daemon_state()
    # Detect agenda .docx in session folder
    _agenda_path = _find_agenda_docx(config.session_folder)
    if _agenda_path:
        misc_state.agenda_docx_path = _agenda_path
        log.info("session", f"Agenda: {_agenda_path.name}")
    # Publish initial session state to daemon REST router
    session_shared_state.set_active_session(_active_session_id, session_name)
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
                session_folder_str = str(config.session_folder) if config.session_folder else None
                addon_bridge_client.send_session_started(participant_join_link, session_folder_str)

    _bridge.set_on_connection_change(_on_addon_connection_change)
    _bridge.start()

    server_disconnected = False
    last_detected_date: date | None = None
    last_heartbeat_at = 0.0
    last_ws_ping_at = 0.0
    last_session_check_at = 0.0
    last_transcript_stats_at = 0.0
    last_transcript_line_count = -1
    last_slides_payload_hash: str | None = None
    last_slides_mtime_scan_at = 0.0

    _prev_overlay_connected: bool = False
    # Restore session state from persisted snapshot if active session exists
    startup_session_state: dict = {}
    try:
        if session_name:
            startup_session_state = load_session_state(sessions_root / session_name)
            if startup_session_state:
                log.info("session", f"Loaded {SESSION_STATE_FILENAME} for restore ({len(startup_session_state)} keys)")
                _apply_runtime_snapshot_restore(startup_session_state)
        if _active_session_id:
            announce_session_id(_active_session_id)
    except Exception as e:
        log.error("session", f"Initial sync failed: {e}")

    # Boot-time GDrive URL resolve: live-resolve from DriveFS into in-memory
    # session_shared_state. Never persisted — the URL is cheap to look up and
    # persisting it caused stale-URL leakage when the resume path didn't refresh.
    if session_name and config.session_folder:
        _boot_gdrive_url = _resolve_gdrive_url(config.session_folder)
        if _boot_gdrive_url:
            session_shared_state.set_gdrive_url(_boot_gdrive_url)
            log.info("session", f"Google Drive: {_boot_gdrive_url}")
        else:
            session_shared_state.set_gdrive_url(None)
            log.error("session", "Google Drive not available at boot — start GDrive to enable the folder link")

    _prev_slides_history_count = len(misc_state.slides_viewed)

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
        if not session_name:
            return
        try:
            if _active_session_id:
                announce_session_id(_active_session_id)
            log.info("session", f"Sent active session to backend: '{session_name}'")
        except Exception as e:
            log.error("session", f"Session re-sync on reconnect failed: {e}")
        # notes/summary counts are already included in GET /api/participant/state
        # so no broadcast needed on reconnect — participants fetch state on load.
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
            # Connectivity state derived from WS connection (no HTTP polling needed).
            ws_connected = ws_client.connected
            if not ws_connected:
                if not server_disconnected:
                    log.error("daemon", "Server unreachable.")
                    server_disconnected = True
                time.sleep(DAEMON_POLL_INTERVAL)
                continue
            if server_disconnected:
                log.info("daemon", "Reconnected to server.")
                server_disconnected = False

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
                                "slug": _target["slug"],
                                "page": _slide_num,
                            }
                            if misc_state.current_slide != _sc:
                                misc_state.current_slide = _sc
                                from daemon.slides.models import CurrentSlide
                                from daemon.ws_messages import SlidesCurrentMsg
                                ws_publish.broadcast(SlidesCurrentMsg(current_slide=CurrentSlide(**_sc)))
                                log.info("addons   ", f"← Slide: {_deck}:{_slide_num}")

            # ── Process slides_viewed deltas from addon bridge ──
            for _sv_batch in _bridge.drain_slides_viewed():
                from daemon.slides.merge_viewed import merge_slides_viewed
                _slug_map = {
                    v.get("source_name", ""): k
                    for k, v in misc_state.slides_catalog.items()
                    if v.get("source_name")
                }
                merge_slides_viewed(misc_state.slides_viewed, _sv_batch, _slug_map)
            _slides_history_count_after = len(misc_state.slides_viewed)
            if _slides_history_count_after != _prev_slides_history_count:
                from daemon.ws_messages import SlidesHistoryCountUpdatedMsg
                ws_publish.broadcast(SlidesHistoryCountUpdatedMsg(count=_slides_history_count_after))
                _prev_slides_history_count = _slides_history_count_after

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
                _WS_APP_PING_INTERVAL = 25.0  # keep Railway proxy from closing idle WS
                if now - last_ws_ping_at >= _WS_APP_PING_INTERVAL:
                    ws_client.send({"type": "daemon_ping"})
                    last_ws_ping_at = now

                # ── Read git activity from file ──
                # ── Check for session management requests ──
                try:
                    session_req = session_pending.pop("session_request")
                    action = session_req.get("action") if session_req else None
                    if action == "create" and session_req is not None:
                        name = session_req["name"]
                        sid = session_req.get("session_id")
                        session_type = session_req.get("type", "workshop")
                        did_sync_in_create = False
                        if sid:
                            set_current_session_id(sid)
                            _active_session_id = sid
                        folder = sessions_root / name
                        # Endpoint may have already pre-created the folder (so DriveFS
                        # can sync it before returning). It tells us whether the folder
                        # existed before that, so we can still distinguish fresh from resume.
                        if "existed" in session_req:
                            existed = bool(session_req["existed"])
                        else:
                            existed = folder.exists()
                        folder.mkdir(parents=True, exist_ok=True)
                        if sid:
                            save_session_meta(folder, {"session_id": sid, "session_type": session_type})
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
                        if not session_name:
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
                            from daemon.qa.state import qa_state as _qa_state
                            from daemon.quiz.state import quiz_state as _quiz_state
                            from daemon.scores import scores as _scores_state
                            from daemon.wordcloud.state import wordcloud_state as _wordcloud_state

                            _participant_state.reset(mode="talk" if session_type == "talk" else "workshop")
                            _wordcloud_state.clear()
                            _qa_state.clear()
                            _misc_state.reset_for_new_session()
                            _quiz_state.clear()
                            _codereview_state.clear()
                            _debate_state.reset()
                            _leaderboard_state.reset()
                            _scores_state.reset()
                            restore_snapshot = _without_session_id(load_session_state(folder))
                            # gdrive_url is live-resolved by the create/resume endpoint
                            # and kept in session_shared_state only (never persisted).
                            _new_gdrive_url = session_req.get("gdrive_url")
                            session_shared_state.set_gdrive_url(_new_gdrive_url)
                            if _new_gdrive_url:
                                log.info("session", f"Google Drive: {_new_gdrive_url}")
                            runtime_session_snapshot = restore_snapshot
                            _apply_runtime_snapshot_restore(restore_snapshot)
                            last_session_state_hash = _state_hash(runtime_session_snapshot)

                            session_name = name
                            _do_save_daemon_state()
                            notes_file = find_notes_in_folder(folder)
                            if notes_file:
                                notes_lines = len(notes_file.read_text(encoding="utf-8", errors="replace").splitlines())
                                log.info("session", f"Notes found ({notes_lines} lines): {notes_file.name}")
                            config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                            # Refresh agenda for new session
                            _agenda_path = _find_agenda_docx(folder)
                            if _agenda_path:
                                _misc_state.agenda_docx_path = _agenda_path
                                log.info("session", f"Agenda refreshed: {_agenda_path.name}")
                            else:
                                _misc_state.agenda_docx_path = None
                                log.info("session", "No agenda found in new session folder")
                            if _active_session_id:
                                announce_session_id(_active_session_id)
                            did_sync_in_create = True
                            # mode_changed removed — host.js/participant.js don't handle it; mode is in full state on reconnect
                            transcript_state.reset()
                        if not did_sync_in_create:
                            # Resume may arrive when session_name is already set in memory
                            # (e.g. after daemon restart with stale state restore). Ensure
                            # active session id is persisted/broadcast even in that path.
                            _do_save_daemon_state()
                            if _active_session_id:
                                announce_session_id(_active_session_id)
                        participant_join_link = (
                            f"{config.server_url}/{_active_session_id}"
                            if _active_session_id
                            else f"{config.server_url}/"
                        )
                        # Notify addons of session start
                        from daemon import addon_bridge_client
                        session_folder_str = str(config.session_folder) if config.session_folder else None
                        addon_bridge_client.send_session_started(participant_join_link, session_folder_str)
                        log.info("addons   ", f"→ started session {participant_join_link}")
                        log.info(
                            "session",
                            f"Session: {name}",
                        )

                    elif action == "end" and session_name:
                        runtime_session_snapshot = _build_runtime_session_snapshot(
                            session_name=session_name,
                        )
                        last_session_state_hash, wrote = _flush_session_state_backup(
                            sessions_root=sessions_root,
                            session_name=session_name,
                            session_snapshot=runtime_session_snapshot,
                            last_flushed_hash=last_session_state_hash,
                            force=True,
                        )
                        if wrote:
                            log.info("session", f"Forced flush {SESSION_STATE_FILENAME} for {session_name}")
                        old_session_name = session_name
                        # Main session ended — clear everything
                        session_name = None
                        config = dc_replace(config, session_folder=None, session_notes=None)
                        _active_session_id = None
                        session_shared_state.set_gdrive_url(None)
                        # Notify addons that session ended
                        from daemon import addon_bridge_client
                        addon_bridge_client.send_session_ended()
                        log.info("session", f"Ended: {old_session_name}")
                        _do_save_daemon_state()
                        if pending_global_state is None:
                            pending_global_state = _build_global_state()
                        last_global_state_hash, _ = _flush_global_state_backup(
                            sessions_root=sessions_root,
                            global_state=pending_global_state,
                            last_flushed_hash=last_global_state_hash,
                            force=True,
                        )
                        announce_session_cleared()
                        transcript_state.reset()

                    elif action == "rename" and session_req is not None:
                        new_name = session_req["name"]
                        if session_name:
                            old_name = session_name
                            new_folder = sessions_root / new_name
                            new_folder.mkdir(parents=True, exist_ok=True)
                            session_name = new_name
                            _do_save_daemon_state()
                            notes_file = find_notes_in_folder(new_folder)
                            config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                            if _active_session_id:
                                announce_session_id(_active_session_id)
                            log.info("session", f"Renamed: {old_name} → {new_name}")

                    elif action == "pause" and session_name:
                        _do_save_daemon_state()
                        log.info("session", f"Paused: {session_name}")

                    elif action == "resume" and session_name:
                        _do_save_daemon_state()
                        resume_folder = sessions_root / session_name
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
                        if _active_session_id:
                            announce_session_id(_active_session_id)
                        transcript_state.reset()
                        # Notify addons of session resume
                        participant_join_link = (
                            f"{config.server_url}/{_active_session_id}"
                            if _active_session_id
                            else f"{config.server_url}/"
                        )
                        from daemon import addon_bridge_client
                        session_folder_str = str(config.session_folder) if config.session_folder else None
                        addon_bridge_client.send_session_started(participant_join_link, session_folder_str)
                        log.info("addons   ", f"→ started session {participant_join_link}")
                        log.info("session", f"Session: {session_name}")

                except Exception as e:
                    log.error("session", f"Request error: {e}")

                # ── Re-detect session folder on date change or if notes not yet found (every 5s) ──
                today = date.today()
                config, last_detected_date, last_session_check_at, _ = (
                    _refresh_session_folder_binding(
                        config=config,
                        sessions_root=sessions_root,
                        session_name=session_name,
                        today=today,
                        last_detected_date=last_detected_date,
                        last_session_check_at=last_session_check_at,
                        now_mono=now,
                    )
                )
                notes_summary_probe = _build_notes_summary_probe(config.session_folder)
                if notes_summary_probe_prev != notes_summary_probe:
                    change_parts = _probe_change_parts(notes_summary_probe_prev, notes_summary_probe)
                    _log_notes_summary_probe(
                        "change-detected",
                        notes_summary_probe,
                        change_parts,
                    )
                    notes_summary_probe_prev = notes_summary_probe
                    # Keep the served agenda path live so a .docx dropped mid-session is
                    # picked up without a daemon restart (mirrors notes/summary handling).
                    misc_state.agenda_docx_path = _agenda_path_from_probe(notes_summary_probe)
                    _broadcast_notes_summary_counts(notes_summary_probe, change_parts)

                if now - last_persist_poll_at >= 3.0:
                    last_persist_poll_at = now
                    if session_name:
                        runtime_session_snapshot = _build_runtime_session_snapshot(
                            session_name=session_name,
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
                        session_name=session_name,
                        session_snapshot=runtime_session_snapshot,
                        last_flushed_hash=last_session_state_hash,
                        force=False,
                    )


                # ── Push session info when changed, on reconnect, or periodically ──
                current_slides = load_slides_manifest(config.session_folder)
                current_slides_hash = hashlib.sha256(
                    json.dumps(current_slides, sort_keys=True).encode("utf-8")
                ).hexdigest()
                slides_changed = current_slides_hash != last_slides_payload_hash

                if slides_changed:
                    last_slides_payload_hash = current_slides_hash

                # notes_content send removed: notes are no longer pushed via WS

                # ── Scan PPTX mtimes every 10s — detect slide updates quickly ──
                if slides_runner and now - last_slides_mtime_scan_at >= 10.0:
                    last_slides_mtime_scan_at = now
                    if slides_runner.scan_pptx_mtimes():
                        from daemon.slides.router import _broadcast_slides_updated
                        _broadcast_slides_updated()

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
                        pass
                    except SystemExit:
                        pass
                    except Exception as e:
                        log.error("transcript", f"Error: {e}")

                # ── Drain stale summary force/reset requests (no longer used) ──
                _pending_requests.pop("summary_full_reset", None)
                _pending_requests.pop("summary_force", None)

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
                log.error("daemon", f"Server error: {e}")
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
