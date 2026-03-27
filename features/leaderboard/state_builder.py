"""Leaderboard state builder — contributes leaderboard state to participant and host state messages."""
from core.state import state


def _build_leaderboard_data() -> tuple[list[dict], int, dict[str, int]]:
    """Build leaderboard entries, total count, and rank map."""
    from core.names import compute_letter_avatar

    all_participants = [
        (uid, state.scores.get(uid, 0))
        for uid in state.participants
        if not uid.startswith("__")
    ]
    all_participants.sort(key=lambda x: (-x[1], state.participant_names.get(x[0], "")))
    top5 = all_participants[:5]

    entries = []
    for rank_idx, (uid, score) in enumerate(top5):
        name = state.participant_names.get(uid, "Unknown")
        universe = state.participant_universes.get(uid, "")
        avatar = state.participant_avatars.get(uid, "")
        if avatar.startswith("letter:"):
            parts = avatar.split(":", 2)
            letter = parts[1] if len(parts) > 1 else "??"
            color = parts[2] if len(parts) > 2 else "hsl(0,60%,50%)"
        else:
            letter, color = compute_letter_avatar(name)
        entries.append({
            "rank": rank_idx + 1,
            "name": name,
            "universe": universe,
            "score": score,
            "letter": letter,
            "color": color,
            "avatar": avatar,
        })

    total = len([uid for uid in state.participants if not uid.startswith("__")])
    all_scored = [
        (uid, state.scores.get(uid, 0))
        for uid in state.participants
        if not uid.startswith("__")
    ]
    all_scored.sort(key=lambda x: (-x[1], state.participant_names.get(x[0], "")))
    rank_map = {uid: idx + 1 for idx, (uid, _) in enumerate(all_scored)}

    return entries, total, rank_map


def build_for_participant(pid: str) -> dict:
    if not state.leaderboard_active:
        return {"leaderboard_active": False, "leaderboard_data": None}
    entries, total, rank_map = _build_leaderboard_data()
    return {
        "leaderboard_active": state.leaderboard_active,
        "leaderboard_data": {
            "entries": entries,
            "total_participants": total,
            "your_rank": rank_map.get(pid),
            "your_score": state.scores.get(pid, 0),
            "your_name": state.participant_names.get(pid, ""),
        },
    }


def build_for_host() -> dict:
    if not state.leaderboard_active:
        return {"leaderboard_active": False, "leaderboard_data": None}
    entries, total, rank_map = _build_leaderboard_data()
    return {
        "leaderboard_active": state.leaderboard_active,
        "leaderboard_data": {
            "entries": entries,
            "total_participants": total,
        },
    }


from core.messaging import register_state_builder
register_state_builder("leaderboard", build_for_participant, build_for_host)
