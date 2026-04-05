"""Daemon emoji reaction router — participant endpoint."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.participant.state import participant_state
from daemon.ws_messages import EmojiReactionMsg
from daemon.ws_publish import notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class EmojiReactionRequest(BaseModel):
    emoji: str

class OkResponse(BaseModel):
    ok: bool = True


participant_router = APIRouter(prefix="/api/participant/emoji", tags=["emoji"])


@participant_router.post("/reaction")
async def emoji_reaction(request: Request, body: EmojiReactionRequest):
    """Participant sends an emoji reaction."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    emoji = body.emoji.strip()
    if not emoji or len(emoji) > 4:
        return JSONResponse({"error": "Invalid emoji"}, status_code=400)

    # Forward to desktop overlay via addons bridge WS — fire and forget
    from daemon import addon_bridge_client
    sent = addon_bridge_client.send_emoji(emoji)
    participant_name = participant_state.participant_names.get(
        pid, "Host" if pid == "__host__" else pid
    )
    if not sent:
        logger.warning("Overlay emoji drop: bridge disconnected pid=%s emoji=%r", pid, emoji)
        daemon_log.info("addon-bridge", f"Dropped reaction from {participant_name!r}: {emoji!r} (bridge unavailable)")
    else:
        daemon_log.info("addon-bridge", f"{participant_name!r} reacted {emoji!r}")

    # Forward to host browser (local WS)
    await notify_host(EmojiReactionMsg(emoji=emoji))

    return OkResponse()
