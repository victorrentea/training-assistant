"""Code review state builder — contributes codereview state to participant and host state messages."""
from core.state import state


def _participant_ids() -> list[str]:
    """Local helper to avoid circular import with core/messaging.py."""
    from core.messaging import participant_ids
    return participant_ids()


def build_for_participant(pid: str) -> dict:
    if state.codereview_snippet is None:
        return {"codereview": None}
    pids = _participant_ids()
    total = len(pids)
    line_percentages = {}
    if state.codereview_phase == "reviewing" and total > 0:
        for p in pids:
            for line in state.codereview_selections.get(p, set()):
                line_percentages[str(line)] = line_percentages.get(str(line), 0) + 1
        line_percentages = {k: round(v * 100 / total) for k, v in line_percentages.items()}
    return {
        "codereview": {
            "snippet": state.codereview_snippet,
            "language": state.codereview_language,
            "phase": state.codereview_phase,
            "my_selections": sorted(state.codereview_selections.get(pid, set())),
            "confirmed_lines": sorted(state.codereview_confirmed),
            "line_percentages": line_percentages,
        }
    }


def build_for_host() -> dict:
    if state.codereview_snippet is None:
        return {"codereview": None}
    pids = _participant_ids()
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
    for key in line_participants:
        line_participants[key].sort(key=lambda x: x["score"])
    return {
        "codereview": {
            "snippet": state.codereview_snippet,
            "language": state.codereview_language,
            "phase": state.codereview_phase,
            "line_counts": line_counts,
            "confirmed_lines": sorted(state.codereview_confirmed),
            "line_participants": line_participants,
            "participant_count": len(pids),
        }
    }


from core.messaging import register_state_builder
register_state_builder("codereview", build_for_participant, build_for_host)
