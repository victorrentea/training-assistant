"""Daemon word cloud router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.wordcloud.state import wordcloud_state
from daemon.ws_messages import WordcloudUpdatedMsg, ScoresUpdatedMsg
from daemon.ws_publish import broadcast_event, broadcast

logger = logging.getLogger(__name__)


class OkResponse(BaseModel):
    ok: bool = True


class SubmitWordBody(BaseModel):
    word: str


class SetTopicBody(BaseModel):
    topic: str


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/wordcloud", tags=["wordcloud"])


@participant_router.post("/word")
async def submit_word(request: Request, body: SubmitWordBody):
    """Participant submits a word to the word cloud."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    word = body.word.strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "wordcloud":
        return JSONResponse({"error": "Word cloud not active"}, status_code=409)

    snapshot = wordcloud_state.add_word(word)

    scores.add_score(pid, 200)
    request.state.write_back_events = [
        broadcast_event(WordcloudUpdatedMsg(**snapshot)),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]

    return OkResponse()


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/wordcloud/word') which expands to /api/{session_id}/wordcloud/word.
# The prefix includes {session_id} path parameter to match this pattern.

host_router = APIRouter(prefix="/api/{session_id}/host/wordcloud", tags=["wordcloud"])


@host_router.post("/word")
async def host_submit_word(body: SubmitWordBody):
    """Host submits a word — same as participant but no scoring."""
    word = body.word.strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    snapshot = wordcloud_state.add_word(word)
    _send_wordcloud_events(snapshot)
    return OkResponse()


@host_router.post("/topic")
async def set_topic(body: SetTopicBody):
    """Host sets the word cloud topic."""
    topic = body.topic.strip()
    snapshot = wordcloud_state.set_topic(topic)
    _send_wordcloud_events(snapshot)
    return OkResponse()


@host_router.post("/clear")
async def clear_wordcloud():
    """Host clears the word cloud."""
    snapshot = wordcloud_state.clear()
    _send_wordcloud_events(snapshot)
    return OkResponse()


def _send_wordcloud_events(snapshot: dict):
    """Send broadcast directly via publisher (host-direct path)."""
    broadcast(WordcloudUpdatedMsg(**snapshot))
