"""Daemon word cloud router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.wordcloud.state import wordcloud_state

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting events."""
    global _ws_client
    _ws_client = client


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/wordcloud", tags=["wordcloud"])


@participant_router.post("/word")
async def submit_word(request: Request):
    """Participant submits a word to the word cloud."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    word = str(body.get("word", "")).strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "wordcloud":
        return JSONResponse({"error": "Word cloud not active"}, status_code=409)

    snapshot = wordcloud_state.add_word(word)

    scores.add_score(pid, 200)
    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "wordcloud_updated", **snapshot}},
        {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}},
    ]

    return JSONResponse({"ok": True})


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/wordcloud/word') which expands to /api/{session_id}/wordcloud/word.
# The prefix includes {session_id} path parameter to match this pattern.

host_router = APIRouter(prefix="/api/{session_id}/wordcloud", tags=["wordcloud"])


@host_router.post("/word")
async def host_submit_word(request: Request):
    """Host submits a word — same as participant but no scoring."""
    body = await request.json()
    word = str(body.get("word", "")).strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    snapshot = wordcloud_state.add_word(word)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


@host_router.post("/topic")
async def set_topic(request: Request):
    """Host sets the word cloud topic."""
    body = await request.json()
    topic = str(body.get("topic", "")).strip()
    snapshot = wordcloud_state.set_topic(topic)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


@host_router.post("/clear")
async def clear_wordcloud(request: Request):
    """Host clears the word cloud."""
    snapshot = wordcloud_state.clear()
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


def _send_wordcloud_events(snapshot: dict):
    """Send broadcast directly via ws_client (host-direct path)."""
    if _ws_client is None:
        return
    _ws_client.send({
        "type": "broadcast",
        "event": {"type": "wordcloud_updated", **snapshot},
    })
