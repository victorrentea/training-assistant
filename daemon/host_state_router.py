"""Daemon host state router — full state for host page load and WS reconnect."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.poll.state import poll_state
from daemon.wordcloud.state import wordcloud_state
from daemon.qa.state import qa_state
from daemon.codereview.state import codereview_state
from daemon.debate.state import debate_state
from daemon.misc.state import misc_state
from daemon.leaderboard.state import leaderboard_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/{session_id}/host", tags=["host-state"])


def _build_host_participants_list() -> list[dict]:
    """Build participant list for host — all named, including offline."""
    ps = participant_state
    all_pids = sorted(
        ps.participant_names.keys(),
        key=lambda pid: (-ps.scores.get(pid, 0), ps.participant_names.get(pid, ""), pid),
    )
    result = []
    for pid in all_pids:
        if pid.startswith("__"):
            continue
        entry = {
            "uuid": pid,
            "name": ps.participant_names.get(pid, f"Guest {pid[:8]}"),
            "score": ps.scores.get(pid, 0),
            "location": ps.locations.get(pid, ""),
            "avatar": ps.participant_avatars.get(pid, ""),
        }
        # Include paste texts if present (from misc_state)
        paste_entries = misc_state.paste_texts.get(pid, [])
        if paste_entries:
            entry["paste_texts"] = paste_entries
        result.append(entry)
    return result


def _build_qa_for_host() -> list[dict]:
    """Build QA question list for host (no personalisation — shows all info)."""
    ps = participant_state
    questions = []
    for qid, q in sorted(
        qa_state.questions.items(),
        key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
    ):
        questions.append({
            "id": qid,
            "text": q["text"],
            "author": ps.participant_names.get(q["author"], "Unknown"),
            "author_uuid": q["author"],
            "author_avatar": ps.participant_avatars.get(q["author"], ""),
            "upvote_count": len(q["upvoters"]),
            "upvoters": list(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
        })
    return questions


def _build_codereview_for_host() -> dict:
    """Build codereview state for host — includes all selections with counts."""
    cr = codereview_state
    result = {
        "snippet": cr.snippet,
        "language": cr.language,
        "phase": cr.phase,
        "confirmed_lines": sorted(cr.confirmed),
        "selections": {pid: sorted(lines) for pid, lines in cr.selections.items()},
    }
    if cr.phase in ("reviewing",) and cr.snippet:
        line_count = len(cr.snippet.splitlines())
        total_participants = max(1, len([
            p for p in cr.selections if not p.startswith("__")
        ]))
        line_percentages: dict[int, int] = {}
        line_counts: dict[int, int] = {}
        for line_idx in range(line_count):
            sel_count = sum(1 for sels in cr.selections.values() if line_idx in sels)
            line_counts[line_idx] = sel_count
            line_percentages[line_idx] = round(sel_count * 100 / total_participants)
        result["line_percentages"] = line_percentages
        result["line_counts"] = line_counts
    return result


def _build_debate_for_host() -> dict:
    """Build debate state for host — full snapshot with side counts."""
    snap = debate_state.snapshot()
    for_count = sum(1 for s in debate_state.sides.values() if s == "for")
    against_count = sum(1 for s in debate_state.sides.values() if s == "against")
    snap["debate_side_counts"] = {"for": for_count, "against": against_count}
    return snap


def _build_poll_for_host() -> dict:
    """Build full poll state for host — includes all votes."""
    ps = poll_state
    return {
        "poll": ps.poll,
        "poll_active": ps.poll_active,
        "vote_counts": ps.vote_counts() if ps.poll else {},
        "votes": dict(ps.votes),
        "poll_timer_seconds": ps.poll_timer_seconds,
        "poll_timer_started_at": ps.poll_timer_started_at.isoformat() if ps.poll_timer_started_at else None,
        "poll_correct_ids": ps.poll_correct_ids,
    }


def _get_current_session_id() -> str | None:
    try:
        from daemon.session_state import get_current_session_id
        return get_current_session_id()
    except Exception:
        return None


@router.get("/state")
async def get_host_state(request: Request, session_id: str):
    """Return full state for host page load — replicates Railway build_for_host()."""
    ps = participant_state
    participant_count = len([p for p in ps.participant_names if not p.startswith("__")])

    wc = wordcloud_state
    poll_data = _build_poll_for_host()
    cr = _build_codereview_for_host()
    debate = _build_debate_for_host()

    state_msg = {
        "type": "state",
        # Core
        "mode": ps.mode,
        "current_activity": ps.current_activity,
        "participant_count": participant_count,
        "participants": _build_host_participants_list(),
        "daemon_connected": True,
        # Wordcloud
        "wordcloud_words": wc.words,
        "wordcloud_word_order": wc.word_order,
        "wordcloud_topic": wc.topic,
        # QA
        "qa_questions": _build_qa_for_host(),
        # Poll
        **poll_data,
        # Codereview
        "codereview": cr,
        # Debate (flattened)
        "debate_statement": debate.get("statement"),
        "debate_phase": debate.get("phase"),
        "debate_side_counts": debate.get("debate_side_counts"),
        "debate_sides": debate.get("sides", {}),
        "debate_arguments": debate.get("arguments", []),
        "debate_champions": debate.get("champions", {}),
        "debate_auto_assigned": debate.get("auto_assigned", []),
        "debate_first_side": debate.get("first_side"),
        "debate_round_index": debate.get("round_index"),
        "debate_round_timer_seconds": debate.get("round_timer_seconds"),
        "debate_round_timer_started_at": debate.get("round_timer_started_at"),
        # Slides + session info (from misc state)
        "slides_current": misc_state.slides_current,
        "session_main": misc_state.session_main,
        "session_name": misc_state.session_name,
        # Session tracking
        "session_id": _get_current_session_id(),
        "daemon_session_folder": None,   # daemon doesn't currently expose this via state endpoint
        "daemon_session_notes": None,
        # Leaderboard
        "leaderboard_active": leaderboard_state.active,
        "leaderboard_data": leaderboard_state.data,
        # Summary / notes
        "summary_points": misc_state.summary_points,
        "notes_content": misc_state.notes_content,
        # Token usage
        "token_usage": _get_token_usage(),
        # Transcript info
        "transcript_line_count": 0,
        "transcript_total_lines": 0,
        "transcript_latest_ts": None,
        # Quiz preview
        "quiz_preview": None,
    }

    return JSONResponse(state_msg)


def _get_token_usage() -> dict:
    """Get token usage from LLM adapter if available."""
    try:
        from daemon.llm.adapter import get_usage
        return get_usage().to_dict()
    except Exception:
        return {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
