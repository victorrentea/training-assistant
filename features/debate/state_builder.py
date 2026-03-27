"""Debate state builder — contributes debate state to participant and host state messages."""
from core.state import state


def build_for_participant(pid: str) -> dict:
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
                "author": "🤖 AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "is_own": a["author_uuid"] == pid,
                "has_upvoted": pid in a["upvoters"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
            for a in sorted(state.debate_arguments, key=lambda a: len(a["upvoters"]), reverse=True)
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
        "debate_my_is_champion": state.debate_champions.get(my_side) == pid if my_side else False,
        "debate_first_side": state.debate_first_side,
        "debate_round_index": state.debate_round_index,
        "debate_round_timer_seconds": state.debate_round_timer_seconds,
        "debate_round_timer_started_at": state.debate_round_timer_started_at.isoformat() if state.debate_round_timer_started_at else None,
    }


def build_for_host() -> dict:
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
                "author": "🤖 AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
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


from core.messaging import register_state_builder
register_state_builder("debate", build_for_participant, build_for_host)
