"""Serialization/deserialization of activity state fields for persistence.

Handles converting Python sets, datetimes, and enums to/from JSON-compatible strings.
"""

import json
from datetime import datetime

from state import ActivityType


def _iso_or_none(dt):
    """Convert a datetime to ISO string, or return None."""
    return dt.isoformat() if dt else None


def _parse_iso_or_none(s):
    """Parse an ISO datetime string back to datetime, or return None."""
    return datetime.fromisoformat(s) if s else None


def serialize_activity_state(state) -> dict[str, str]:
    """Serialize activity-related fields from AppState to a dict of key -> JSON string."""
    result = {}

    # Simple scalars
    result["current_activity"] = json.dumps(state.current_activity.value)
    result["leaderboard_active"] = json.dumps(state.leaderboard_active)

    # Poll
    result["poll"] = json.dumps({
        "poll": state.poll,
        "poll_active": state.poll_active,
        "votes": state.votes,
        "poll_correct_ids": state.poll_correct_ids,
        "poll_opened_at": _iso_or_none(state.poll_opened_at),
        "poll_timer_seconds": state.poll_timer_seconds,
        "poll_timer_started_at": _iso_or_none(state.poll_timer_started_at),
    })

    # Word cloud
    result["wordcloud"] = json.dumps({
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_word_order": state.wordcloud_word_order,
        "wordcloud_topic": state.wordcloud_topic,
    })

    # Q&A — convert upvoters sets to lists
    qa_serializable = {}
    for qid, q in state.qa_questions.items():
        qa_serializable[qid] = {
            **q,
            "upvoters": list(q.get("upvoters", set())),
        }
    result["qa"] = json.dumps({"qa_questions": qa_serializable})

    # Code Review — convert sets to lists
    codereview_selections = {
        uuid: list(lines) for uuid, lines in state.codereview_selections.items()
    }
    result["codereview"] = json.dumps({
        "codereview_snippet": state.codereview_snippet,
        "codereview_language": state.codereview_language,
        "codereview_phase": state.codereview_phase,
        "codereview_selections": codereview_selections,
        "codereview_confirmed": list(state.codereview_confirmed),
    })

    # Debate — convert sets to lists, datetimes to ISO
    debate_arguments = []
    for arg in state.debate_arguments:
        debate_arguments.append({
            **arg,
            "upvoters": list(arg.get("upvoters", set())),
        })
    result["debate"] = json.dumps({
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_sides": state.debate_sides,
        "debate_arguments": debate_arguments,
        "debate_champions": state.debate_champions,
        "debate_auto_assigned": list(state.debate_auto_assigned),
        "debate_first_side": state.debate_first_side,
        "debate_round_index": state.debate_round_index,
        "debate_round_timer_seconds": state.debate_round_timer_seconds,
        "debate_round_timer_started_at": _iso_or_none(state.debate_round_timer_started_at),
    })

    return result


def restore_activity_state(state, data: dict[str, str]):
    """Restore activity-related fields from a dict of key -> JSON string into AppState."""

    if "current_activity" in data:
        state.current_activity = ActivityType(json.loads(data["current_activity"]))

    if "leaderboard_active" in data:
        state.leaderboard_active = json.loads(data["leaderboard_active"])

    if "poll" in data:
        poll = json.loads(data["poll"])
        state.poll = poll["poll"]
        state.poll_active = poll["poll_active"]
        state.votes = poll["votes"]
        state.poll_correct_ids = poll["poll_correct_ids"]
        state.poll_opened_at = _parse_iso_or_none(poll["poll_opened_at"])
        state.poll_timer_seconds = poll["poll_timer_seconds"]
        state.poll_timer_started_at = _parse_iso_or_none(poll["poll_timer_started_at"])

    if "wordcloud" in data:
        wc = json.loads(data["wordcloud"])
        state.wordcloud_words = wc["wordcloud_words"]
        state.wordcloud_word_order = wc["wordcloud_word_order"]
        state.wordcloud_topic = wc["wordcloud_topic"]

    if "qa" in data:
        qa = json.loads(data["qa"])
        qa_questions = {}
        for qid, q in qa["qa_questions"].items():
            qa_questions[qid] = {
                **q,
                "upvoters": set(q.get("upvoters", [])),
            }
        state.qa_questions = qa_questions

    if "codereview" in data:
        cr = json.loads(data["codereview"])
        state.codereview_snippet = cr["codereview_snippet"]
        state.codereview_language = cr["codereview_language"]
        state.codereview_phase = cr["codereview_phase"]
        state.codereview_selections = {
            uuid: set(lines) for uuid, lines in cr["codereview_selections"].items()
        }
        state.codereview_confirmed = set(cr["codereview_confirmed"])

    if "debate" in data:
        db = json.loads(data["debate"])
        state.debate_statement = db["debate_statement"]
        state.debate_phase = db["debate_phase"]
        state.debate_sides = db["debate_sides"]
        state.debate_champions = db["debate_champions"]
        state.debate_auto_assigned = set(db["debate_auto_assigned"])
        state.debate_first_side = db["debate_first_side"]
        state.debate_round_index = db["debate_round_index"]
        state.debate_round_timer_seconds = db["debate_round_timer_seconds"]
        state.debate_round_timer_started_at = _parse_iso_or_none(db["debate_round_timer_started_at"])
        # Restore arguments with upvoters as sets
        debate_arguments = []
        for arg in db["debate_arguments"]:
            debate_arguments.append({
                **arg,
                "upvoters": set(arg.get("upvoters", [])),
            })
        state.debate_arguments = debate_arguments
