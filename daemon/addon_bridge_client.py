"""WS client connecting to the local addons WebSocket server (wispr-flow/ws_server.py).

The addons server runs at ws://127.0.0.1:<WS_SERVER_PORT> (default 8765).

Protocol:
  Daemon → Addons: {"type": "emoji", "emoji": "<char>", "count": 1}
              — relayed by addons to the desktop overlay for animation
  Addons → Daemon: {"type": "slide", "deck": "<name>", "slide": <n>, "presenting": <bool>}
              — pushed on every PowerPoint slide/deck change (no message when unchanged)
  On connect:  server immediately sends the last known slide state as a welcome message.
"""
import json
import os
import queue
import threading

from daemon import log

_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))
_RECONNECT_INTERVAL = 5.0  # seconds between reconnect attempts
_OPEN_TIMEOUT = 5.0
_NAME = "addon-bridge"


class AddonBridgeClient:
    def __init__(self):
        self._ws = None
        self._ws_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._slide_queue: queue.Queue = queue.Queue()
        self._on_connection_change: callable | None = None

    # ── Public API (callable from any thread) ─────────────────────────────────

    @property
    def connected(self) -> bool:
        with self._ws_lock:
            return self._ws is not None

    def set_on_connection_change(self, callback: callable) -> None:
        """callback(connected: bool) — called from WS thread on state change."""
        self._on_connection_change = callback

    def send_emoji(self, emoji: str) -> bool:
        """Forward an emoji reaction to the overlay. Best-effort; never raises."""
        return self._send({"type": "emoji", "emoji": emoji, "count": 1})

    def drain_slides(self) -> list[dict]:
        """Return all pending slide events. Call from the main thread each loop."""
        events: list[dict] = []
        while True:
            try:
                events.append(self._slide_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=_NAME)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._ws_lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send(self, msg: dict) -> bool:
        with self._ws_lock:
            if self._ws is None:
                return False
            try:
                self._ws.send(json.dumps(msg))
                return True
            except Exception:
                return False

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as e:
                log.error(_NAME, f"Unexpected error: {e}")
            if not self._stop.is_set():
                self._stop.wait(_RECONNECT_INTERVAL)

    def _connect_and_listen(self) -> None:
        from websockets.sync.client import connect as ws_connect
        from websockets.exceptions import ConnectionClosed

        url = f"ws://127.0.0.1:{_PORT}"
        try:
            ws = ws_connect(url, open_timeout=_OPEN_TIMEOUT)
        except Exception:
            # Bridge not running yet — silent retry
            return

        with self._ws_lock:
            self._ws = ws
        log.info(_NAME, f"Connected to {url}")
        self._fire_connection_change(True)

        try:
            for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if data.get("type") == "slide":
                    self._slide_queue.put(data)
        except ConnectionClosed:
            pass
        finally:
            with self._ws_lock:
                self._ws = None
            log.info(_NAME, "Disconnected")
            self._fire_connection_change(False)

    def _fire_connection_change(self, connected: bool) -> None:
        if self._on_connection_change:
            try:
                self._on_connection_change(connected)
            except Exception:
                pass


# ── Module-level singleton — set by __main__.py on startup ───────────────────

_client: AddonBridgeClient | None = None


def set_client(client: AddonBridgeClient) -> None:
    global _client
    _client = client


def get_client() -> AddonBridgeClient | None:
    return _client


def is_connected() -> bool:
    return _client is not None and _client.connected


def send_emoji(emoji: str) -> bool:
    """Best-effort emoji send to addons overlay. Returns True if sent."""
    return _client is not None and _client.send_emoji(emoji)
