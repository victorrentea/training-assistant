"""Daemon emoji reaction router — participant endpoint."""
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.emoji.catalog import ALLOWED_EMOJI
from daemon.emoji.rate_limit import SlidingWindowRateLimiter
from daemon.participant.state import participant_state
from daemon.ws_messages import EmojiCountersUpdatedMsg, EmojiReactionMsg
from daemon.ws_publish import broadcast, notify_host
from railway.shared.throttle import AsyncThrottle

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class EmojiReactionRequest(BaseModel):
    emoji: str

class OkResponse(BaseModel):
    ok: bool = True

class EmojiGlobalStateResponse(BaseModel):
    emoji_global_enabled: bool


# Allow a burst of up to 15 reactions, but no more than 15 per rolling minute
# from a single participant — keyed by participant id (the host is exempt).
EMOJI_RATE_LIMIT = 15
EMOJI_RATE_WINDOW_S = 60.0
emoji_rate_limiter = SlidingWindowRateLimiter(EMOJI_RATE_LIMIT, EMOJI_RATE_WINDOW_S)


participant_router = APIRouter(prefix="/api/participant/emoji", tags=["emoji"])


async def _broadcast_emoji_counters_now() -> None:
    counters = dict(participant_state.emoji_counters)
    broadcast(EmojiCountersUpdatedMsg(counters=counters))
    # Persist to session-state.json
    from daemon.misc.content_files import get_active_session_folder
    from daemon.session_state import save_session_state
    folder = get_active_session_folder()
    if folder:
        save_session_state(folder, participant_state.snapshot())


_emoji_throttle = AsyncThrottle(0.5, _broadcast_emoji_counters_now)


@participant_router.post("/reaction", status_code=204)
async def emoji_reaction(request: Request, body: EmojiReactionRequest):
    """Participant sends an emoji reaction."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    emoji = body.emoji.strip()
    if emoji not in ALLOWED_EMOJI:
        # Reject anything not offered by the UI — the catalog is the whitelist.
        return JSONResponse({"error": "Emoji not allowed"}, status_code=400)

    # Master switch off: silently drop before any forwarding (host screen +
    # desktop overlay) or counting. 204 is indistinguishable from success, so
    # the participant's local float animation still plays and they stay unaware.
    if not participant_state.emoji_global_enabled:
        return Response(status_code=204)

    # Throttle bursts: cap each participant at 15 reactions/minute (host exempt).
    if not pid.startswith("__") and not emoji_rate_limiter.allow(pid):
        return JSONResponse({"error": "Too many reactions"}, status_code=429)

    # Forward to desktop overlay via addons bridge WS — fire and forget
    from daemon import addon_bridge_client
    sent = addon_bridge_client.send_emoji(emoji)
    participant_name = participant_state.participant_names.get(
        pid, "Host" if pid == "__host__" else pid
    )
    if not sent:
        logger.warning("Overlay emoji drop: bridge disconnected pid=%s emoji=%r", pid, emoji)
        daemon_log.info("addons   ", f"✗ reaction from {participant_name!r}: {emoji!r} (bridge unavailable)")
    else:
        daemon_log.info("addons   ", f"→ {participant_name!r} reacted {emoji!r}")

    # Forward to host browser (local WS)
    await notify_host(EmojiReactionMsg(emoji=emoji))

    # In talk mode: update cumulative counter and broadcast to all participants
    if participant_state.mode == "talk":
        participant_state.emoji_counters[emoji] = participant_state.emoji_counters.get(emoji, 0) + 1
        _emoji_throttle.schedule()

    return Response(status_code=204)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/emoji", tags=["emoji"])


@host_router.post("/global-toggle", response_model=EmojiGlobalStateResponse)
async def toggle_emoji_global():
    """Host flips the session-wide emoji master switch and persists it."""
    participant_state.emoji_global_enabled = not participant_state.emoji_global_enabled
    enabled = participant_state.emoji_global_enabled

    from daemon.misc.content_files import get_active_session_folder
    from daemon.session_state import save_session_state
    folder = get_active_session_folder()
    if folder:
        save_session_state(folder, participant_state.snapshot())

    daemon_log.info("emoji  ", f"❤️ reactions {'enabled' if enabled else 'disabled'} (master switch)")
    return EmojiGlobalStateResponse(emoji_global_enabled=enabled)
