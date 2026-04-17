import base64
import hmac
import json
import logging
import os

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from railway.shared.state import state

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_svix(request: Request, body_bytes: bytes) -> bool:
    """Verify Svix webhook signature (used by AgentMail)."""
    secret = os.environ.get("AGENTMAIL_WEBHOOK_SECRET", "")
    if not secret:
        return False
    key = base64.b64decode(secret.removeprefix("whsec_"))
    msg_id = request.headers.get("svix-id", "")
    timestamp = request.headers.get("svix-timestamp", "")
    signed = f"{msg_id}.{timestamp}.".encode() + body_bytes
    expected_sig = base64.b64encode(hmac.new(key, signed, "sha256").digest()).decode()
    for sig in request.headers.get("svix-signature", "").split(" "):
        if sig.startswith("v1,") and hmac.compare_digest(sig[3:], expected_sig):
            return True
    return False


@router.post("/webhook/agentmail")
async def agentmail_webhook(request: Request):
    body_bytes = await request.body()
    if not _verify_svix(request, body_bytes):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    body = json.loads(body_bytes)
    if body.get("event_type") != "message.received":
        return {"ok": True, "ignored": True}

    senders = body.get("thread", {}).get("senders", [])
    if not any("victorrentea@gmail.com" in s for s in senders):
        logger.info("inbox: skipping thread not from victorrentea@gmail.com (senders=%s)", senders)
        return {"ok": True, "ignored": True}

    ws = state.claude_inbox_ws
    if ws is not None:
        try:
            await ws.send_text(json.dumps({"type": "email_received"}))
            logger.info("inbox ↓ forwarded email_received to listener")
        except Exception as exc:
            logger.warning("inbox ↓ listener send failed: %s", exc)
            state.claude_inbox_ws = None
            try:
                await ws.close(code=1011)
            except Exception:
                pass
    else:
        logger.warning("inbox: no listener connected — event dropped")

    return {"ok": True}


@router.websocket("/ws/claude-inbox")
async def claude_inbox_ws_endpoint(websocket: WebSocket, token: str = ""):
    expected = os.environ.get("CLAUDE_INBOX_WS_TOKEN", "")
    if not expected or not hmac.compare_digest(expected.encode(), token.encode()):
        await websocket.close(code=4003)
        return

    await websocket.accept()
    state.claude_inbox_ws = websocket
    logger.info("inbox: listener connected")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("inbox: listener disconnected")
    finally:
        if state.claude_inbox_ws is websocket:
            state.claude_inbox_ws = None
