"""
Core/infrastructure state builder — handles the fields that don't belong to a specific feature:
type, backend_version, mode, my_score, my_avatar, my_name, current_activity, participant_count,
host_connected, overlay_connected, screen_share_active, summary, notes, daemon info, token_usage,
participants list, needs_restore, pending_deploy.
"""
from datetime import datetime, timezone
from core.state import state
from core.version import get_backend_version


def _participant_display_name(pid: str) -> str:
    name = state.participant_names.get(pid, "").strip()
    return name if name else f"Guest {pid[:8]}"


def _build_host_participants_list() -> list[dict]:
    from core.messaging import historical_participant_ids
    from core.state import ActivityType

    include_debate_side = state.current_activity == ActivityType.DEBATE and state.debate_phase
    participants_list: list[dict] = []
    for pid in historical_participant_ids():
        participant = {
            "uuid": pid,
            "name": _participant_display_name(pid),
            "score": state.scores.get(pid, 0),
            "location": state.locations.get(pid, ""),
            "avatar": state.participant_avatars.get(pid, ""),
            "ip": state.participant_ips.get(pid, ""),
            "online": pid in state.participants,
        }
        paste_entries = state.paste_texts.get(pid, [])
        if paste_entries:
            participant["paste_texts"] = paste_entries
        if include_debate_side:
            participant["debate_side"] = state.debate_sides.get(pid)
        participants_list.append(participant)
    return participants_list


def build_for_participant(pid: str) -> dict:
    from core.messaging import participant_ids
    pids = participant_ids()
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "mode": state.mode,
        "my_score": 0 if state.mode == "conference" else state.scores.get(pid, 0),
        "my_avatar": state.participant_avatars.get(pid, ""),
        "my_name": state.participant_names.get(pid, ""),
        "current_activity": state.current_activity,
        "participant_count": len(pids),
        "host_connected": "__host__" in state.participants,
        "summary_points": state.summary_points,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
        "notes_content": state.notes_content,
        "screen_share_active": state.screen_share_active,
        "daemon_connected": last_seen is not None and (now - last_seen).total_seconds() < 5,
    }


def build_for_host() -> dict:
    from core.messaging import participant_ids
    pids = participant_ids()
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    daemon_connected = last_seen is not None and (now - last_seen).total_seconds() < 5
    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "mode": state.mode,
        "current_activity": state.current_activity,
        "participant_count": len(pids),
        "participants": _build_host_participants_list(),
        "overlay_connected": "__overlay__" in state.participants,
        "screen_share_active": state.screen_share_active,
        "summary_points": state.summary_points,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
        "notes_content": state.notes_content,
        "transcript_line_count": state.transcript_line_count,
        "transcript_total_lines": state.transcript_total_lines,
        "transcript_latest_ts": state.transcript_latest_ts,
        "transcript_last_content_at": state.transcript_last_content_at.isoformat() if state.transcript_last_content_at else None,
        "daemon_last_seen": last_seen.isoformat() if last_seen else None,
        "daemon_connected": daemon_connected,
        "daemon_session_folder": state.daemon_session_folder,
        "daemon_session_notes": state.daemon_session_notes,
        "quiz_preview": state.quiz_preview,
        "token_usage": state.token_usage,
        "needs_restore": state.needs_restore,
        "pending_deploy": state.pending_deploy,
    }


from core.messaging import register_state_builder
register_state_builder("core", build_for_participant, build_for_host)
