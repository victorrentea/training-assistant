# daemon/ws_client.py
"""Unified WebSocket client for daemon↔backend communication."""
import base64
import json
import queue
import ssl
import threading
from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed
import os
from daemon import log
from daemon.config import DEFAULT_SERVER_URL

_RECONNECT_INTERVAL = float(os.environ.get("DAEMON_WS_RECONNECT_INTERVAL_SECONDS", "3.0"))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class DaemonWsClient:
    """Single persistent WebSocket connection to backend /ws/daemon.

    Message handlers are called from the main thread via drain_queue().
    The WS receiver thread only enqueues work items.
    """

    def __init__(self):
        self._ws = None
        self._ws_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._handlers: dict[str, callable] = {}
        self._on_connect_callbacks: list[callable] = []
        self._work_queue: queue.Queue = queue.Queue()

    def register_handler(self, msg_type: str, handler: callable):
        """Register a handler for a backend-pushed message type."""
        self._handlers[msg_type] = handler

    def on_connect(self, callback: callable):
        """Register a callback invoked on each (re)connect. Runs on WS thread."""
        self._on_connect_callbacks.append(callback)

    def send(self, msg: dict) -> bool:
        """Send JSON message to backend. Thread-safe."""
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return False
        try:
            ws.send(json.dumps(msg))
            return True
        except Exception:
            return False

    def drain_queue(self):
        """Process all pending work items. Call from main thread each loop iteration."""
        while True:
            try:
                msg_type, data = self._work_queue.get_nowait()
            except queue.Empty:
                break
            handler = self._handlers.get(msg_type)
            if handler:
                try:
                    handler(data)
                except Exception as e:
                    log.error("ws-client", f"Handler error for {msg_type}: {e}")

    def start(self):
        """Start the WS connection thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the WS connection thread."""
        self._stop.set()
        with self._ws_lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def connected(self) -> bool:
        with self._ws_lock:
            return self._ws is not None

    def _run_loop(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as e:
                log.error("ws-client", f"Connection error: {e}")
            if not self._stop.is_set():
                self._stop.wait(_RECONNECT_INTERVAL)

    def _connect_and_listen(self):
        server_url = os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
        host_username = os.environ.get("HOST_USERNAME", "host")
        host_password = os.environ.get("HOST_PASSWORD", "")
        url = server_url.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{url}/ws/daemon"
        creds = base64.b64encode(f"{host_username}:{host_password}".encode()).decode()
        headers = {"Authorization": f"Basic {creds}"}

        _ping_interval = float(os.environ.get("DAEMON_WS_PING_INTERVAL_SECONDS", "20"))
        ws_kwargs = {
            "open_timeout": 10,
            "ping_interval": _ping_interval,
            "ping_timeout": _ping_interval,
        }
        if url.startswith("wss://"):
            ws_kwargs["ssl"] = _ssl_context()

        try:
            ws = ws_connect(url, additional_headers=headers, **ws_kwargs)
        except TypeError as exc:
            if "additional_headers" not in str(exc):
                raise
            ws = ws_connect(url, extra_headers=list(headers.items()), **ws_kwargs)

        with self._ws_lock:
            self._ws = ws

        log.info("ws-client", f"Connected to {url}")

        # Fire on_connect callbacks
        for cb in self._on_connect_callbacks:
            try:
                cb()
            except Exception as e:
                log.error("ws-client", f"on_connect error: {e}")

        try:
            for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                msg_type = data.get("type")
                if msg_type == "kicked":
                    log.info("ws-client", "Kicked by server (new daemon connected)")
                    break
                if msg_type in self._handlers:
                    # Enqueue for main thread processing
                    self._work_queue.put((msg_type, data))
                elif msg_type == "slide_log":
                    # Logging can happen on WS thread (no shared state mutation)
                    log.info("ws-client", f"slide_log: {data.get('event')} {data.get('slug')}")
        except ConnectionClosed:
            pass
        finally:
            with self._ws_lock:
                self._ws = None
            log.info("ws-client", "Disconnected")
