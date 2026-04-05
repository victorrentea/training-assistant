"""Typed WebSocket publisher — all WS message sends go through here.

This module is the single choke point for outbound WS messages.
It ensures every message is a Pydantic BaseModel instance (validated at construction),
then serializes to dict before sending over the wire.

The CI guard test (test_ws_contract.py::test_no_raw_ws_sends) ensures no code
bypasses this module by calling _ws_client.send() or send_to_host() directly.
"""
import json
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None
_host_ws = None


def set_ws_client(client):
    """Set the WebSocket client for broadcasting to Railway."""
    global _ws_client
    _ws_client = client


def set_host_ws(ws):
    """Store the host browser's WS connection."""
    global _host_ws
    _host_ws = ws


def clear_host_ws():
    """Clear the host WS reference."""
    global _host_ws
    _host_ws = None


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
    _ws_client.send({"type": "broadcast", "event": msg.model_dump()})


async def notify_host(msg: BaseModel):
    """Send typed message to host browser via direct WS."""
    if _host_ws is None:
        return
    try:
        await _host_ws.send_text(json.dumps(msg.model_dump()))
    except Exception:
        logger.debug("Failed to send to host WS")


def broadcast_event(msg: BaseModel) -> dict:
    """Build a write_back_events entry for participant broadcast."""
    return {"type": "broadcast", "event": msg.model_dump()}


def host_event(msg: BaseModel) -> dict:
    """Build a write_back_events entry for host notification."""
    return {"type": "send_to_host", "event": msg.model_dump()}
