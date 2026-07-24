"""Daemon attention-bell router — participant endpoint (Direction B).

Mirrors ``daemon/emoji/router.py``: resolve the caller name from the
``X-Participant-ID`` header, log who + when on the ``addons`` channel, forward a
``bell_ring`` to the macOS overlay (best-effort), and optionally notify the host
browser (dual-render). Gated behind the ``attention_enabled`` master switch —
the endpoint rejects/ignores rings while the capability is disabled, before
resolving, logging, forwarding, or notifying.
"""
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from daemon import log as daemon_log
from daemon.emoji.rate_limit import SlidingWindowRateLimiter
from daemon.participant.state import participant_state
from daemon.ws_messages import BellRungMsg
from daemon.ws_publish import notify_host

logger = logging.getLogger(__name__)


# Allow a small burst of rings, but no more than this per rolling minute from a
# single participant — keyed by participant id (the host is exempt).
BELL_RATE_LIMIT = 6
BELL_RATE_WINDOW_S = 60.0
bell_rate_limiter = SlidingWindowRateLimiter(BELL_RATE_LIMIT, BELL_RATE_WINDOW_S)

# When True, also notify the host browser so it can render an incoming bell in
# addition to the overlay card (dual-render, mirroring emoji).
HOST_DUAL_RENDER = True


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

    # Server-side rate limit protects the host's overlay from spam (host exempt).
    if not pid.startswith("__") and not bell_rate_limiter.allow(pid):
        return JSONResponse({"error": "Too many rings"}, status_code=429)

    caller = participant_state.participant_names.get(pid, pid)
    daemon_log.info("addons   ", f"🔔 {caller!r} rang the bell")

    # Forward to the desktop overlay via the addons bridge — best-effort.
    from daemon import addon_bridge_client
    sent = addon_bridge_client.send_bell(caller)
    if not sent:
        logger.warning("Overlay bell drop: bridge disconnected pid=%s", pid)
        daemon_log.info("addons   ", f"✗ bell from {caller!r} (bridge unavailable)")

    # Optional dual-render: let the host browser page surface the bell too.
    if HOST_DUAL_RENDER:
        await notify_host(BellRungMsg(caller=caller))

    return Response(status_code=204)
