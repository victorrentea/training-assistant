"""State snapshot endpoints for daemon-based persistence.

GET /api/state-snapshot — serialize all persistent state to JSON + MD5 hash
POST /api/state-restore — restore state from a snapshot dict
"""

import hashlib
import json
import logging
from datetime import datetime

from fastapi import APIRouter

from messaging import broadcast_state
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)

SPECIAL_PIDS = {"__host__", "__overlay__"}


def _iso_or_none(dt):
    """Convert a datetime to ISO string, or return None."""
    return dt.isoformat() if dt else None


def _parse_iso_or_none(s):
    """Parse an ISO datetime string back to datetime, or return None."""
    return datetime.fromisoformat(s) if s else None


def _serialize_state() -> dict:
    """Serialize all persistent AppState fields to a JSON-compatible dict."""
    # Participants — filter out special PIDs
    participant_names = {k: v for k, v in state.participant_names.items() if k not in SPECIAL_PIDS}
    participant_avatars = {k: v for k, v in state.participant_avatars.items() if k not in SPECIAL_PIDS}
    participant_universes = {k: v for k, v in state.participant_universes.items() if k not in SPECIAL_PIDS}
    scores = {k: v for k, v in state.scores.items() if k not in SPECIAL_PIDS}
    locations = {k: v for k, v in state.locations.items() if k not in SPECIAL_PIDS}

    # Q&A — convert upvoters sets to sorted lists (sorted for deterministic hashing)
    qa_serializable = {}
    for qid, q in state.qa_questions.items():
        qa_serializable[qid] = {
            **q,
            "upvoters": sorted(q.get("upvoters", set())),
        }

    # Code Review — convert sets to sorted lists
    codereview_selections = {
        uuid: sorted(lines) for uuid, lines in state.codereview_selections.items()
    }

    # Debate — convert sets to sorted lists, datetimes to ISO
    debate_arguments = []
    for arg in state.debate_arguments:
        debate_arguments.append({
            **arg,
            "upvoters": sorted(arg.get("upvoters", set())),
        })

    return {
        # Participants
        "participant_names": participant_names,
        "participant_avatars": participant_avatars,
        "participant_universes": participant_universes,
        "scores": scores,
        "locations": locations,
        # Mode & activity
        "mode": state.mode,
        "current_activity": state.current_activity.value,
        "leaderboard_active": state.leaderboard_active,
        # Poll
        "poll": state.poll,
        "poll_active": state.poll_active,
        "votes": state.votes,
        "poll_correct_ids": state.poll_correct_ids,
        "poll_opened_at": _iso_or_none(state.poll_opened_at),
        "poll_timer_seconds": state.poll_timer_seconds,
        "poll_timer_started_at": _iso_or_none(state.poll_timer_started_at),
        # Word cloud
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_word_order": state.wordcloud_word_order,
        "wordcloud_topic": state.wordcloud_topic,
        # Q&A
        "qa_questions": qa_serializable,
        # Code Review
        "codereview_snippet": state.codereview_snippet,
        "codereview_language": state.codereview_language,
        "codereview_phase": state.codereview_phase,
        "codereview_selections": codereview_selections,
        "codereview_confirmed": sorted(state.codereview_confirmed),
        # Debate
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_sides": state.debate_sides,
        "debate_arguments": debate_arguments,
        "debate_champions": state.debate_champions,
        "debate_auto_assigned": sorted(state.debate_auto_assigned),
        "debate_first_side": state.debate_first_side,
        "debate_round_index": state.debate_round_index,
        "debate_round_timer_seconds": state.debate_round_timer_seconds,
        "debate_round_timer_started_at": _iso_or_none(state.debate_round_timer_started_at),
        # Summary
        "summary_points": state.summary_points,
        "slides_current": state.slides_current,
        # Needs restore flag
        "needs_restore": state.needs_restore,
    }


@router.get("/api/state-snapshot")
async def get_state_snapshot():
    """Serialize all persistent state to JSON with MD5 hash."""
    state_dict = _serialize_state()
    state_json = json.dumps(state_dict, sort_keys=True)
    md5_hex = hashlib.md5(state_json.encode()).hexdigest()
    return {"hash": md5_hex, "state": state_dict}


@router.post("/api/state-restore")
async def restore_state_snapshot(body: dict):
    """Restore state from a snapshot dict."""
    data = body.get("state", body)

    # Participants
    if "participant_names" in data:
        state.participant_names = data["participant_names"]
    if "participant_avatars" in data:
        state.participant_avatars = data["participant_avatars"]
    if "participant_universes" in data:
        state.participant_universes = data["participant_universes"]
    if "scores" in data:
        state.scores = data["scores"]
    if "locations" in data:
        state.locations = data["locations"]

    # Mode & activity
    if "mode" in data:
        state.mode = data["mode"]
    if "current_activity" in data:
        state.current_activity = ActivityType(data["current_activity"])
    if "leaderboard_active" in data:
        state.leaderboard_active = data["leaderboard_active"]

    # Poll
    if "poll" in data:
        state.poll = data["poll"]
    if "poll_active" in data:
        state.poll_active = data["poll_active"]
    if "votes" in data:
        state.votes = data["votes"]
    if "poll_correct_ids" in data:
        state.poll_correct_ids = data["poll_correct_ids"]
    if "poll_opened_at" in data:
        state.poll_opened_at = _parse_iso_or_none(data["poll_opened_at"])
    if "poll_timer_seconds" in data:
        state.poll_timer_seconds = data["poll_timer_seconds"]
    if "poll_timer_started_at" in data:
        state.poll_timer_started_at = _parse_iso_or_none(data["poll_timer_started_at"])

    # Word cloud
    if "wordcloud_words" in data:
        state.wordcloud_words = data["wordcloud_words"]
    if "wordcloud_word_order" in data:
        state.wordcloud_word_order = data["wordcloud_word_order"]
    if "wordcloud_topic" in data:
        state.wordcloud_topic = data["wordcloud_topic"]

    # Q&A — convert upvoters lists back to sets
    if "qa_questions" in data:
        qa_questions = {}
        for qid, q in data["qa_questions"].items():
            qa_questions[qid] = {
                **q,
                "upvoters": set(q.get("upvoters", [])),
            }
        state.qa_questions = qa_questions

    # Code Review — convert lists back to sets
    if "codereview_snippet" in data:
        state.codereview_snippet = data["codereview_snippet"]
    if "codereview_language" in data:
        state.codereview_language = data["codereview_language"]
    if "codereview_phase" in data:
        state.codereview_phase = data["codereview_phase"]
    if "codereview_selections" in data:
        state.codereview_selections = {
            uuid: set(lines) for uuid, lines in data["codereview_selections"].items()
        }
    if "codereview_confirmed" in data:
        state.codereview_confirmed = set(data["codereview_confirmed"])

    # Debate — convert lists back to sets, ISO strings back to datetimes
    if "debate_statement" in data:
        state.debate_statement = data["debate_statement"]
    if "debate_phase" in data:
        state.debate_phase = data["debate_phase"]
    if "debate_sides" in data:
        state.debate_sides = data["debate_sides"]
    if "debate_champions" in data:
        state.debate_champions = data["debate_champions"]
    if "debate_auto_assigned" in data:
        state.debate_auto_assigned = set(data["debate_auto_assigned"])
    if "debate_first_side" in data:
        state.debate_first_side = data["debate_first_side"]
    if "debate_round_index" in data:
        state.debate_round_index = data["debate_round_index"]
    if "debate_round_timer_seconds" in data:
        state.debate_round_timer_seconds = data["debate_round_timer_seconds"]
    if "debate_round_timer_started_at" in data:
        state.debate_round_timer_started_at = _parse_iso_or_none(data["debate_round_timer_started_at"])
    if "debate_arguments" in data:
        debate_arguments = []
        for arg in data["debate_arguments"]:
            debate_arguments.append({
                **arg,
                "upvoters": set(arg.get("upvoters", [])),
            })
        state.debate_arguments = debate_arguments

    # Summary
    if "summary_points" in data:
        state.summary_points = data["summary_points"]
    if "slides_current" in data:
        state.slides_current = data["slides_current"]

    # Mark as restored
    state.needs_restore = False

    await broadcast_state()

    # Count restored participants
    restored_count = len(state.participant_names)
    logger.info("State restored with %d participants", restored_count)

    return {"ok": True, "restored_participants": restored_count}
