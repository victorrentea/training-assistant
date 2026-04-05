"""Daemon emoji reaction router — participant endpoint."""
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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

    # Forward to host browser (local WS)
    await notify_host(EmojiReactionMsg(emoji=emoji))

    # Forward to desktop overlay (victor-macos-addons) — fire and forget
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:56789/emoji",
                              json={"emoji": emoji}, timeout=1.0)
    except Exception:
        pass  # overlay may not be running

    return OkResponse()
