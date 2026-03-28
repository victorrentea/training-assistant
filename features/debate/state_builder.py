"""Debate state builder — contributes debate state to participant and host state messages."""
from core.state import state


def _build_debate_state(pid: str | None = None) -> dict:
    result = {
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_side_counts": {
            "for": sum(1 for s in state.debate_sides.values() if s == "for"),
            "against": sum(1 for s in state.debate_sides.values() if s == "against"),
        },
        "debate_arguments": [
            _build_argument(a, pid)
            for a in sorted(state.debate_arguments, key=lambda a: len(a["upvoters"]), reverse=True)
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
        "debate_first_side": state.debate_first_side,
        "debate_round_index": state.debate_round_index,
        "debate_round_timer_seconds": state.debate_round_timer_seconds,
        "debate_round_timer_started_at": state.debate_round_timer_started_at.isoformat() if state.debate_round_timer_started_at else None,
    }
    if pid is not None:
        my_side = state.debate_sides.get(pid)
        result["debate_my_side"] = my_side
        result["debate_auto_assigned"] = pid in state.debate_auto_assigned
        result["debate_my_is_champion"] = state.debate_champions.get(my_side) == pid if my_side else False
    return result


def _build_argument(a: dict, pid: str | None = None) -> dict:
    entry = {
        "id": a["id"],
        "text": a["text"],
        "side": a["side"],
        "author": "🤖 AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
        "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
        "ai_generated": a["ai_generated"],
        "upvote_count": len(a["upvoters"]),
        "merged_into": a.get("merged_into"),
    }
    if pid is not None:
        entry["is_own"] = a["author_uuid"] == pid
        entry["has_upvoted"] = pid in a["upvoters"]
    return entry


def build_for_participant(pid: str) -> dict:
    if not state.debate_statement:
        return {}
    return _build_debate_state(pid)


def build_for_host() -> dict:
    if not state.debate_statement:
        return {}
    return _build_debate_state()


from core.messaging import register_state_builder
register_state_builder("debate", build_for_participant, build_for_host)
