import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import WebSocket

from backend_version import get_backend_version
from state import state


def participant_names() -> list[str]:
    return sorted(n for n in state.participants if n != "__host__")


def build_state_message() -> dict:
    names = participant_names()
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    daemon_connected = last_seen is not None and (now - last_seen).total_seconds() < 5
    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "participant_count": len(names),
        "participant_names": names,
        "participant_locations": {n: state.locations.get(n, "") for n in names},
        "daemon_last_seen": last_seen.isoformat() if last_seen else None,
        "daemon_connected": daemon_connected,
        "quiz_preview": state.quiz_preview,
        "scores": state.scores,
        "current_activity": state.current_activity,
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_topic": state.wordcloud_topic,
        "qa_questions": [
            {
                "id": qid,
                "text": q["text"],
                "author": q["author"],
                "upvote_count": len(q["upvoters"]),
                "upvoters": list(q["upvoters"]),
                "answered": q["answered"],
                "timestamp": q["timestamp"],
            }
            for qid, q in sorted(
                state.qa_questions.items(),
                key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"])
            )
        ],
    }


async def broadcast(message: dict, exclude: Optional[str] = None):
    dead = []
    for name, ws in state.participants.items():
        if name == exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(name)
    for name in dead:
        state.participants.pop(name, None)


async def send_state_to(ws: WebSocket):
    await ws.send_text(json.dumps(build_state_message()))
