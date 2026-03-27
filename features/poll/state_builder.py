"""Poll state builder — contributes poll/vote state to participant and host state messages."""
from core.state import state, ActivityType


def _voted_ids_for(pid: str) -> list[str] | None:
    """Return the participant's voted option IDs as a list, or None if not voted."""
    if state.poll_correct_ids is None:
        return None
    selection = state.votes.get(pid)
    if selection is None:
        return None
    ids = selection if isinstance(selection, list) else [selection]
    return list(ids)


def build_for_participant(pid: str) -> dict:
    return {
        "poll": state.poll,
        "poll_active": state.poll_active,
        "poll_timer_seconds": state.poll_timer_seconds,
        "poll_timer_started_at": state.poll_timer_started_at.isoformat() if state.poll_timer_started_at else None,
        "vote_counts": state.vote_counts(),
        "my_vote": state.votes.get(pid),
        "poll_correct_ids": state.poll_correct_ids,
        "my_voted_ids": _voted_ids_for(pid),
    }


def build_for_host() -> dict:
    return {
        "poll": state.poll,
        "poll_active": state.poll_active,
        "poll_timer_seconds": state.poll_timer_seconds,
        "poll_timer_started_at": state.poll_timer_started_at.isoformat() if state.poll_timer_started_at else None,
        "vote_counts": state.vote_counts(),
    }


from core.messaging import register_state_builder
register_state_builder("poll", build_for_participant, build_for_host)
