"""Tablet ⇄ Mac add-on WebSocket bridge (last-resort internet transport).

Lets the Android LaunchBreak tablet reach the Mac add-on's HTTP API over the
internet when the two can't reach each other on the LAN (public-Wi-Fi client
isolation / mDNS filtering) and there's no USB cable attached.

Both sides connect **out** to Railway, so neither needs an inbound port — which
is exactly what defeats client isolation and NAT: only outbound connections are
required, and every captive/guest network allows those.

    Mac add-on  ── wss ──▶  /ws/bridge/mac     (stays connected, one at a time)
    Tablet      ── wss ──▶  /ws/bridge/tablet  (stays connected)

Relay protocol (mirrors ``features/ws/proxy_bridge.py``):
    tablet → backend → mac:  {"type":"bridge_request","id":<hex>,"method":"GET",
                              "path":"/sound/play/40_joker.mp3?vol=80","body":""}
    mac → backend → tablet:  {"type":"bridge_response","id":<hex>,"status":200,
                              "contentType":"application/json","body":"{...}"}

The backend is a dumb pipe: it forwards ``bridge_request`` frames to the single
connected Mac and routes each ``bridge_response`` back to the tablet waiting on
its correlation id. The Mac runs the request through its own existing route
table (the same one serving LAN/USB HTTP), so every endpoint works over the
bridge with no per-endpoint code here.

Auth: a shared ``TABLET_BRIDGE_TOKEN`` (env; ``BRIDGE_TOKEN`` accepted as a
fallback), sent as ``?token=`` or the ``X-Bridge-Token`` header. **Fail-closed**
— if it's unset, or a client omits/mismatches it, the connection is refused.
This is the one door from the public internet to Victor's Mac, so it must be
authenticated.
"""
import asyncio
import json
import logging
import os
import secrets
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# The single connected Mac add-on (kick-old-on-reconnect, like /ws/daemon).
_mac_ws: WebSocket | None = None

# correlation id → (tablet WebSocket, created_at monotonic). A tablet request is
# parked here until the Mac's bridge_response with the same id comes back.
_pending: dict[str, tuple[WebSocket, float]] = {}

# Orphan-request TTL: if the Mac never answers (crash / disconnect mid-request),
# drop the parked entry so _pending can't grow without bound. The tablet has its
# own client-side timeout and will retry.
_PENDING_TTL_SECONDS = 30.0

# Serialise all sends across the (few) bridge sockets. Throughput is a human
# pressing soundboard buttons, so a single lock costs nothing and removes any
# risk of two coroutines interleaving frames on the same socket (the tablet loop
# writes to the Mac socket while the Mac loop writes to a tablet socket).
_send_lock = asyncio.Lock()


def _token_ok(websocket: WebSocket) -> bool:
    # TABLET_BRIDGE_TOKEN is the canonical Railway env var; BRIDGE_TOKEN is
    # accepted as a fallback.
    expected = os.environ.get("TABLET_BRIDGE_TOKEN") or os.environ.get("BRIDGE_TOKEN") or ""
    if not expected:
        logger.warning("TABLET_BRIDGE_TOKEN unset — refusing bridge connection (fail-closed)")
        return False
    supplied = (
        websocket.query_params.get("token")
        or websocket.headers.get("x-bridge-token")
        or ""
    )
    return secrets.compare_digest(supplied.encode(), expected.encode())


async def _safe_send(websocket: WebSocket, payload: dict) -> bool:
    async with _send_lock:
        try:
            await websocket.send_text(json.dumps(payload))
            return True
        except Exception:
            return False


def _prune_pending(now: float) -> None:
    stale = [rid for rid, (_, ts) in _pending.items() if now - ts > _PENDING_TTL_SECONDS]
    for rid in stale:
        _pending.pop(rid, None)
    if stale:
        logger.info("Bridge: pruned %d stale request(s)", len(stale))


@router.websocket("/ws/bridge/mac")
async def bridge_mac_endpoint(websocket: WebSocket):
    """The Mac add-on's uplink. Forwards bridge_response frames back to tablets."""
    global _mac_ws
    if not _token_ok(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    # Only one add-on at a time — kick a stale previous connection.
    old = _mac_ws
    if old is not None and old is not websocket:
        try:
            await old.close(code=1001)
        except Exception:
            pass
    _mac_ws = websocket
    logger.info("Bridge: Mac add-on connected")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("type") != "bridge_response":
                continue
            rid = data.get("id")
            entry = _pending.pop(rid, None) if rid else None
            if entry is None:
                continue  # unknown / already-timed-out id
            tablet_ws, _ = entry
            await _safe_send(tablet_ws, data)
    except WebSocketDisconnect:
        pass
    finally:
        if _mac_ws is websocket:
            _mac_ws = None
        logger.info("Bridge: Mac add-on disconnected")


@router.websocket("/ws/bridge/tablet")
async def bridge_tablet_endpoint(websocket: WebSocket):
    """A tablet's uplink. Forwards bridge_request frames to the connected Mac."""
    if not _token_ok(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    logger.info("Bridge: tablet connected")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("type") != "bridge_request":
                continue
            rid = data.get("id")
            if not rid:
                continue
            now = time.monotonic()
            _prune_pending(now)
            mac = _mac_ws
            if mac is None:
                # No Mac connected — answer at once so the tablet fails over fast
                # (falls back to local playback / shows disconnected).
                await _safe_send(websocket, _offline_response(rid, "mac-offline"))
                continue
            _pending[rid] = (websocket, now)
            if not await _safe_send(mac, data):
                _pending.pop(rid, None)
                await _safe_send(websocket, _offline_response(rid, "mac-send-failed"))
    except WebSocketDisconnect:
        pass
    finally:
        # Drop any of this tablet's still-parked requests so _pending stays clean.
        for rid in [rid for rid, (ws, _) in _pending.items() if ws is websocket]:
            _pending.pop(rid, None)
        logger.info("Bridge: tablet disconnected")


def _offline_response(rid: str, reason: str) -> dict:
    return {
        "type": "bridge_response",
        "id": rid,
        "status": 503,
        "contentType": "application/json",
        "body": json.dumps({"ok": False, "reason": reason}),
    }
