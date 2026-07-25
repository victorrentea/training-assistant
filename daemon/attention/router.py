"""Daemon attention router — host master switch + both directions.

Modelled on the emoji feature (``daemon/emoji/router.py``): one module holds the
host router (master switch + Direction A host→participant notifications) and the
participant router (Direction B: the bell). Two deliberate differences from the
emoji master switch: this one defaults OFF, and toggling broadcasts an
``attention_enabled`` message so participants show/hide the bell + permission
affordance live.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from daemon import log as daemon_log
from daemon.emoji.rate_limit import SlidingWindowRateLimiter
from daemon.participant.state import participant_state
from daemon.ws_messages import AttentionEnabledMsg, BellRungMsg, HostNotificationMsg
from daemon.ws_publish import broadcast, notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class AttentionGlobalStateResponse(BaseModel):
    attention_enabled: bool


# Server-side cap on a broadcast host notification. Without it a multi-hundred-KB
# body could be fanned out to every connected participant (amplification / DoS).
HOST_NOTIFICATION_MAX_LEN = 500


class HostNotificationRequest(BaseModel):
    # max_length rejects (422) an over-length body before it is broadcast.
    text: str = Field(max_length=HOST_NOTIFICATION_MAX_LEN)


# ── Host router (called directly on daemon localhost, like the emoji host router) ──

host_router = APIRouter(prefix="/api/{session_id}/host/attention", tags=["attention"])


@host_router.post("/global-toggle", response_model=AttentionGlobalStateResponse)
async def toggle_attention_global():
    """Host flips the session-wide attention master switch, persists it, and
    broadcasts the new state so every connected participant updates live."""
    participant_state.attention_enabled = not participant_state.attention_enabled
    enabled = participant_state.attention_enabled

    participant_state.persist()

    # Live push so the bell button + permission indicator appear/disappear on
    # every participant without a reload. Carries a boolean only — no UUIDs.
    broadcast(AttentionEnabledMsg(enabled=enabled))

    daemon_log.info("host", f"🔔 attention {'enabled' if enabled else 'disabled'} (master switch)")
    return AttentionGlobalStateResponse(attention_enabled=enabled)


@host_router.post("/notify", status_code=204)
async def send_host_notification(body: HostNotificationRequest):
    """Host broadcasts a text notification to all participants (Direction A)."""
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "Empty notification text"}, status_code=400)

    # Defense in depth: refuse to broadcast while the capability is disabled,
    # independent of any UI state (the Send button is also hidden/disabled).
    if not participant_state.attention_enabled:
        return JSONResponse({"error": "Attention capability disabled"}, status_code=409)

    at = datetime.now(timezone.utc).isoformat()
    broadcast(HostNotificationMsg(text=text, at=at))
    daemon_log.info("host", f"🔔 host notification broadcast: {text!r}")
    return Response(status_code=204)


# ── Participant router (Direction B: the bell) ──

# Allow a small burst of rings, but no more than this per rolling minute from a
# single participant — keyed by participant id. Unlike emoji there is NO host
# id exemption: the host page has no bell control, so an exempt id prefix would
# only hand participants a crafted-header bypass of the limit.
BELL_RATE_LIMIT = 6
BELL_RATE_WINDOW_S = 60.0
bell_rate_limiter = SlidingWindowRateLimiter(BELL_RATE_LIMIT, BELL_RATE_WINDOW_S)


participant_router = APIRouter(prefix="/api/participant/bell", tags=["attention"])


@participant_router.post("", status_code=204)
async def ring_bell(request: Request):
    """Participant rings the attention bell (no request body)."""
    # Master switch off: reject/ignore before resolving, logging, forwarding, or
    # notifying — so a hand-crafted POST achieves nothing while disabled.
    if not participant_state.attention_enabled:
        return Response(status_code=204)

    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Server-side rate limit protects the host's overlay from spam.
    if not bell_rate_limiter.allow(pid):
        return JSONResponse({"error": "Too many rings"}, status_code=429)

    # Resolve a human display name. NEVER fall back to the raw pid/UUID — that
    # leaked a UUID onto the projector. An unknown or blank name → "Someone".
    caller = (participant_state.participant_names.get(pid) or "").strip() or "Someone"
    # Anonymous flag via the same explicit signal used for attendees.md: a
    # participant who typed a real name is not anonymous, even if it matches a
    # fictional pool entry.
    anonymous = pid in participant_state.anonymous_pids

    # Forward to the desktop overlay via the addons bridge — best-effort. One
    # `addons` log line per ring, success or drop (mirrors the emoji router).
    from daemon import addon_bridge_client
    sent = addon_bridge_client.send_bell(caller, anonymous)
    if sent:
        daemon_log.info("addons   ", f"🔔 {caller!r} rang the bell")
    else:
        logger.warning("Overlay bell drop: bridge disconnected pid=%s", pid)
        daemon_log.info("addons   ", f"✗ {caller!r} rang the bell (bridge unavailable)")

    # Dual-render: the host browser surfaces the bell too (mirrors emoji_reaction).
    await notify_host(BellRungMsg(caller=caller, anonymous=anonymous))

    return Response(status_code=204)
