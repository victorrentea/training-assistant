"""Q&A state builder — contributes qa_questions to participant and host state messages."""
from core.state import state


def _build_questions(pid: str | None = None) -> list[dict]:
    questions = []
    for qid, q in sorted(
        state.qa_questions.items(),
        key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
    ):
        entry = {
            "id": qid,
            "text": q["text"],
            "author": state.participant_names.get(q["author"], "Unknown"),
            "upvote_count": len(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
            "author_avatar": state.participant_avatars.get(q["author"], ""),
        }
        if pid is not None:
            entry["is_own"] = q["author"] == pid
            entry["has_upvoted"] = pid in q["upvoters"]
        questions.append(entry)
    return questions


def build_for_participant(pid: str) -> dict:
    return {"qa_questions": _build_questions(pid)}


def build_for_host() -> dict:
    return {"qa_questions": _build_questions()}


from core.messaging import register_state_builder
register_state_builder("qa", build_for_participant, build_for_host)
