import json
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import WebSocket

from backend_version import get_backend_version
from state import state, ActivityType

logger = logging.getLogger(__name__)


SPECIAL_PIDS = {"__host__", "__overlay__"}


def participant_ids() -> list[str]:
    """Return sorted UUIDs of named participants, excluding special clients."""
    return sorted(
        pid for pid in state.participants
        if pid not in SPECIAL_PIDS and pid in state.participant_names
    )


def _voted_ids_for(pid: str) -> list[str] | None:
    """Return the participant's voted option IDs as a list, or None if not voted."""
    if state.poll_correct_ids is None:
        return None
    selection = state.votes.get(pid)
    if selection is None:
        return None
    ids = selection if isinstance(selection, list) else [selection]
    return list(ids)


def _build_qa_for_participant(pid: str) -> list[dict]:
    return [
        {
            "id": qid,
            "text": q["text"],
            "author": state.participant_names.get(q["author"], "Unknown"),
            "is_own": q["author"] == pid,
            "has_upvoted": pid in q["upvoters"],
            "upvote_count": len(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
            "author_avatar": state.participant_avatars.get(q["author"], ""),
        }
        for qid, q in sorted(
            state.qa_questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
        )
    ]


def _build_qa_for_host() -> list[dict]:
    return [
        {
            "id": qid,
            "text": q["text"],
            "author": state.participant_names.get(q["author"], "Unknown"),
            "upvote_count": len(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
            "author_avatar": state.participant_avatars.get(q["author"], ""),
        }
        for qid, q in sorted(
            state.qa_questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
        )
    ]


def _build_debate_for_participant(pid: str) -> dict:
    """Build debate state personalized for a participant."""
    if not state.debate_statement:
        return {}
    my_side = state.debate_sides.get(pid)
    return {
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_my_side": my_side,
        "debate_auto_assigned": pid in state.debate_auto_assigned,
        "debate_side_counts": {
            "for": sum(1 for s in state.debate_sides.values() if s == "for"),
            "against": sum(1 for s in state.debate_sides.values() if s == "against"),
        },
        "debate_arguments": [
            {
                "id": a["id"],
                "text": a["text"],
                "side": a["side"],
                "author": "✨ AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "is_own": a["author_uuid"] == pid,
                "has_upvoted": pid in a["upvoters"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
            for a in state.debate_arguments
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
        "debate_my_is_champion": state.debate_champions.get(my_side) == pid if my_side else False,
        "debate_first_side": state.debate_first_side,
        "debate_sub_phase_index": state.debate_sub_phase_index,
        "debate_sub_timer_seconds": state.debate_sub_timer_seconds,
        "debate_sub_timer_started_at": state.debate_sub_timer_started_at.isoformat() if state.debate_sub_timer_started_at else None,
    }


def _build_debate_for_host() -> dict:
    """Build debate state for host."""
    if not state.debate_statement:
        return {}
    return {
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_side_counts": {
            "for": sum(1 for s in state.debate_sides.values() if s == "for"),
            "against": sum(1 for s in state.debate_sides.values() if s == "against"),
        },
        "debate_arguments": [
            {
                "id": a["id"],
                "text": a["text"],
                "side": a["side"],
                "author": "✨ AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
            for a in state.debate_arguments
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
        "debate_first_side": state.debate_first_side,
        "debate_sub_phase_index": state.debate_sub_phase_index,
        "debate_sub_timer_seconds": state.debate_sub_timer_seconds,
        "debate_sub_timer_started_at": state.debate_sub_timer_started_at.isoformat() if state.debate_sub_timer_started_at else None,
    }


def _build_codereview_for_participant(pid: str) -> dict | None:
    if state.codereview_snippet is None:
        return None
    pids = participant_ids()
    total = len(pids)
    line_percentages = {}
    if state.codereview_phase == "reviewing" and total > 0:
        for p in pids:
            for line in state.codereview_selections.get(p, set()):
                line_percentages[str(line)] = line_percentages.get(str(line), 0) + 1
        line_percentages = {k: round(v * 100 / total) for k, v in line_percentages.items()}
    return {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "my_selections": sorted(state.codereview_selections.get(pid, set())),
        "confirmed_lines": sorted(state.codereview_confirmed),
        "line_percentages": line_percentages,
    }


def _build_codereview_for_host() -> dict | None:
    if state.codereview_snippet is None:
        return None
    pids = participant_ids()
    line_counts: dict[str, int] = {}
    line_participants: dict[str, list[dict]] = {}
    for p in pids:
        for line in state.codereview_selections.get(p, set()):
            key = str(line)
            line_counts[key] = line_counts.get(key, 0) + 1
            if key not in line_participants:
                line_participants[key] = []
            line_participants[key].append({
                "uuid": p,
                "name": state.participant_names.get(p, "Unknown"),
                "score": state.scores.get(p, 0),
            })
    # Sort each line's participants by score ascending
    for key in line_participants:
        line_participants[key].sort(key=lambda x: x["score"])
    return {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "line_counts": line_counts,
        "confirmed_lines": sorted(state.codereview_confirmed),
        "line_participants": line_participants,
        "participant_count": len(pids),
    }


def build_participant_state(pid: str) -> dict:
    """Build personalized state for a participant."""
    pids = participant_ids()
    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "participant_count": len(pids),
        "host_connected": "__host__" in state.participants,
        "my_vote": state.votes.get(pid),
        "poll_correct_ids": state.poll_correct_ids,
        "my_voted_ids": _voted_ids_for(pid),
        "my_score": state.scores.get(pid, 0),
        "my_avatar": state.participant_avatars.get(pid, ""),
        "current_activity": state.current_activity,
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_topic": state.wordcloud_topic,
        "summary_points": state.summary_points,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
        "notes_content": state.notes_content,
        "qa_questions": _build_qa_for_participant(pid),
        **_build_debate_for_participant(pid),
        "codereview": _build_codereview_for_participant(pid),
    }


def build_host_state() -> dict:
    """Build full state for the host panel."""
    pids = participant_ids()
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    daemon_connected = last_seen is not None and (now - last_seen).total_seconds() < 5

    participants_list = []
    for pid in pids:
        name = state.participant_names.get(pid, "Unknown")
        loc = state.locations.get(pid, "")
        score = state.scores.get(pid, 0)
        p = {
            "uuid": pid,
            "name": name,
            "score": score,
            "location": loc,
            "avatar": state.participant_avatars.get(pid, ""),
        }
        if state.current_activity == ActivityType.DEBATE and state.debate_phase:
            p["debate_side"] = state.debate_sides.get(pid)  # "for", "against", or None
        participants_list.append(p)

    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "participant_count": len(pids),
        "participants": participants_list,
        "daemon_last_seen": last_seen.isoformat() if last_seen else None,
        "daemon_connected": daemon_connected,
        "daemon_session_folder": state.daemon_session_folder,
        "daemon_session_notes": state.daemon_session_notes,
        "quiz_preview": state.quiz_preview,
        "current_activity": state.current_activity,
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_topic": state.wordcloud_topic,
        "summary_points": state.summary_points,
        "summary_updated_at": state.summary_updated_at.isoformat() if state.summary_updated_at else None,
        "notes_content": state.notes_content,
        "transcript_line_count": state.transcript_line_count,
        "transcript_total_lines": state.transcript_total_lines,
        "transcript_latest_ts": state.transcript_latest_ts,
        "qa_questions": _build_qa_for_host(),
        **_build_debate_for_host(),
        "codereview": _build_codereview_for_host(),
        "overlay_connected": "__overlay__" in state.participants,
    }


async def broadcast_state():
    """Send personalized state to each connected client."""
    dead = []
    for pid, ws in state.participants.items():
        if pid == "__overlay__":
            continue
        try:
            if pid == "__host__":
                await ws.send_text(json.dumps(build_host_state()))
            else:
                await ws.send_text(json.dumps(build_participant_state(pid)))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send identical message to all connected clients."""
    dead = []
    for pid, ws in state.participants.items():
        if pid == exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast_participant_update():
    """Send participant update: simple count to participants, full details to host."""
    pids = participant_ids()
    count = len(pids)

    # Simple message for participants
    participant_msg = json.dumps({"type": "participant_count", "count": count, "host_connected": "__host__" in state.participants})

    # Detailed message for host
    participants_list = []
    for pid in pids:
        name = state.participant_names.get(pid, "Unknown")
        participants_list.append({
            "uuid": pid,
            "name": name,
            "score": state.scores.get(pid, 0),
            "location": state.locations.get(pid, ""),
            "avatar": state.participant_avatars.get(pid, ""),
        })
    host_msg = json.dumps({
        "type": "participant_count",
        "count": count,
        "participants": participants_list,
    })

    dead = []
    for pid, ws in state.participants.items():
        try:
            if pid == "__host__":
                await ws.send_text(host_msg)
            else:
                await ws.send_text(participant_msg)
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def send_state_to_participant(ws: WebSocket, pid: str):
    """Send personalized state to a specific participant."""
    await ws.send_text(json.dumps(build_participant_state(pid)))


async def send_state_to_host(ws: WebSocket):
    """Send host state to the host websocket."""
    await ws.send_text(json.dumps(build_host_state()))


async def send_emoji_to_overlay(emoji: str):
    """Forward an emoji reaction to the overlay client if connected."""
    ws = state.participants.get("__overlay__")
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps({"type": "emoji_reaction", "emoji": emoji}))
    except Exception:
        state.participants.pop("__overlay__", None)
