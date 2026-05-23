"""Typed WebSocket publisher — all WS message sends go through here.

This module is the single choke point for outbound WS messages.
It ensures every message is a Pydantic BaseModel instance (validated at construction),
then serializes to dict before sending over the wire.

The CI guard test (test_ws_contract.py::test_no_raw_ws_sends) ensures no code
bypasses this module by calling _ws_client.send() or send_to_host() directly.
"""
import json

from pydantic import BaseModel

from daemon import log

# Set by __main__.py during daemon startup
_ws_client = None
# Set of active host browser WS connections. Multiple host tabs may be open
# at once (e.g. trainer's main session + a debug tab); notify_host broadcasts
# to all of them so a new tab can't silence pushes to the original.
_host_wss: set = set()


def set_ws_client(client):
    """Set the WebSocket client for broadcasting to Railway."""
    global _ws_client
    _ws_client = client


def set_host_ws(ws):
    """Register a host browser WS connection."""
    _host_wss.add(ws)


def clear_host_ws(ws=None):
    """Unregister a specific host WS, or all if ws=None."""
    if ws is None:
        _host_wss.clear()
    else:
        _host_wss.discard(ws)


def send_to_railway(msg: dict) -> bool:
    """Send a raw dict message to the Railway backend (daemon→Railway protocol messages).

    Use this for daemon-internal protocol messages (e.g. download_pdf, code_timestamp).
    For participant/host broadcasts use broadcast() / notify_host() instead.
    Returns True if sent, False if not connected.
    """
    if _ws_client is None:
        return False
    return _ws_client.send(msg)


def broadcast(msg: BaseModel):
    """Send typed message to all participants via Railway broadcast."""
    if _ws_client is None:
        return
    event = msg.model_dump()
    msg_type = event.get("type", "unknown")
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("daemon.ws_publish")
        with tracer.start_as_current_span(f"broadcast:{msg_type}"):
            from daemon.telemetry.ws_propagation import inject_trace_context
            inject_trace_context(event)
            _ws_client.send({"type": "broadcast", "event": event})
    except ImportError:
        _ws_client.send({"type": "broadcast", "event": event})


async def notify_host(msg: BaseModel):
    """Send typed message to every connected host browser WS."""
    if not _host_wss:
        return
    event = msg.model_dump()
    msg_type = event.get("type", "unknown")
    log.debug("host", f"← {msg_type}")
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("daemon.ws_publish")
        with tracer.start_as_current_span(f"notify_host:{msg_type}"):
            from daemon.telemetry.ws_propagation import inject_trace_context
            inject_trace_context(event)
            payload = json.dumps(event)
    except ImportError:
        payload = json.dumps(event)
    # Iterate over a snapshot so concurrent clear_host_ws is safe.
    dead = []
    for ws in list(_host_wss):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _host_wss.discard(ws)


def broadcast_event(msg: BaseModel) -> dict:
    """Build a write_back_events entry for participant broadcast."""
    event = msg.model_dump()
    try:
        from daemon.telemetry.ws_propagation import inject_trace_context
        inject_trace_context(event)
    except ImportError:
        pass
    return {"type": "broadcast", "event": event}
