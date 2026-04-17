import hmac
import json
import logging
import os

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from railway.shared.state import state

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook/agentmail")
async def agentmail_webhook(request: Request):
    expected = os.environ.get("AGENTMAIL_WEBHOOK_SECRET", "")
    incoming = request.headers.get("x-webhook-secret", "")
    if not expected or not hmac.compare_digest(expected.encode(), incoming.encode()):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    body = await request.json()
    if body.get("event_type") != "message.received":
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
