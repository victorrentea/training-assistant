"""Daemon attention router — host master switch + host→participant notifications.

This is Direction A of the attention feature (host → all participants) plus the
shared master enable-gate. Direction B (participant → host bell) lives in
``daemon/bell/router.py``. Modelled on the emoji master switch
(``daemon/emoji/router.py``), with two deliberate differences: the switch
defaults OFF and it broadcasts an ``attention_enabled`` message so participants
show/hide the bell + permission affordance live.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon import log as daemon_log
from daemon.participant.state import participant_state
from daemon.ws_messages import AttentionEnabledMsg, HostNotificationMsg
from daemon.ws_publish import broadcast


# ── Pydantic models ──

class AttentionGlobalStateResponse(BaseModel):
    attention_enabled: bool


class HostNotificationRequest(BaseModel):
    text: str


# ── Host router (called directly on daemon localhost, like the emoji host router) ──

host_router = APIRouter(prefix="/api/{session_id}/host/attention", tags=["attention"])


def _persist_state() -> None:
    from daemon.misc.content_files import get_active_session_folder
    from daemon.session_state import save_session_state
    folder = get_active_session_folder()
    if folder:
        save_session_state(folder, participant_state.snapshot())


@host_router.post("/global-toggle", response_model=AttentionGlobalStateResponse)
async def toggle_attention_global():
    """Host flips the session-wide attention master switch, persists it, and
    broadcasts the new state so every connected participant updates live."""
    participant_state.attention_enabled = not participant_state.attention_enabled
    enabled = participant_state.attention_enabled

    _persist_state()

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
