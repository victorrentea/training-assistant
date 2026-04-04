"""State snapshot helpers for daemon-based persistence.

Serialization and restore logic used by the daemon WebSocket protocol.
HTTP endpoints were removed — daemon communicates via WS only.
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from core.state import state, ActivityType

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
        # Summary
        "summary_points": state.summary_points,
        "slides_current": state.slides_current,
        # Session identity — must be preserved so URLs like /host/{id} survive restarts
        "session_id": state.session_id,
        "session_name": state.session_name,
        # Needs restore flag
        "needs_restore": state.needs_restore,
    }


def restore_state_from_dict(data: dict):
    """Restore state from a snapshot dict (called from WS handler)."""
    # Participants
    if "participant_names" in data:
        state.participant_names = data["participant_names"]
    if "participant_avatars" in data:
        state.participant_avatars = data["participant_avatars"]
    if "participant_universes" in data:
        state.participant_universes = data["participant_universes"]
    # scores are owned by daemon — not restored here (daemon restores its own scores)
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

    # Summary
    if "summary_points" in data:
        state.summary_points = data["summary_points"]
    if "slides_current" in data:
        state.slides_current = data["slides_current"]

    # Mark as restored
    state.needs_restore = False

    restored_count = len(state.participant_names)
    logger.info("State restored with %d participants", restored_count)
    return restored_count
