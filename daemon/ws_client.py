# daemon/ws_client.py
"""Unified WebSocket client for daemon↔backend communication."""
import base64
import json
import os
import queue
import re
import ssl
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from daemon import log
from daemon.config import DEFAULT_SERVER_URL

_RECONNECT_INTERVAL = float(os.environ.get("DAEMON_WS_RECONNECT_INTERVAL_SECONDS", "3.0"))
_NOISY_PROXY_MSG_TYPES = frozenset({"proxy_request", "proxy_response", "slide_log"})


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
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._inline_handlers: set[str] = set()
        self._on_connect_callbacks: list[Callable[..., Any]] = []
        self._work_queue: queue.Queue = queue.Queue()

    def register_handler(self, msg_type: str, handler: Callable[..., Any], *, inline: bool = False):
        """Register a handler for a backend-pushed message type."""
        self._handlers[msg_type] = handler
        if inline:
            self._inline_handlers.add(msg_type)
        else:
            self._inline_handlers.discard(msg_type)

    def on_connect(self, callback: Callable[..., Any]):
        """Register a callback invoked on each (re)connect. Runs on WS thread."""
        self._on_connect_callbacks.append(callback)

    def send(self, msg: dict) -> bool:
        """Send JSON message to backend. Thread-safe.

        The lock is held for the entire send to prevent ConcurrencyError from
        concurrent thread pool workers (websockets.sync raises ConcurrencyError
        if two threads call ws.send() simultaneously).
        """
        with self._ws_lock:
            if self._ws is None:
                return False
            try:
                if self._should_trace_msg(msg):
                    log.debug("railway", f"↑ {self._msg_name(msg)}")
                self._ws.send(json.dumps(msg))
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
                    log.error("railway", f"Handler error for {msg_type}: {e}")

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
                log.error("railway", f"Connection error: {e}")
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
        # Keep ping_timeout wider than ping_interval so a single lost pong
        # (Railway edge jitter) doesn't tear the connection down.
        _ping_timeout = float(os.environ.get("DAEMON_WS_PING_TIMEOUT_SECONDS", "60"))
        ws_kwargs = {
            "open_timeout": 10,
            "ping_interval": _ping_interval,
            "ping_timeout": _ping_timeout,
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

        log.info("railway", f"Connected to {url}")

        # Fire on_connect callbacks
        for cb in self._on_connect_callbacks:
            try:
                cb()
            except Exception as e:
                log.error("railway", f"on_connect error: {e}")

        close_info = "no-close-frame"
        try:
            for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                msg_type = data.get("type")
                if self._should_trace_msg(data):
                    log.debug("railway", f"↓ {self._msg_name(data)}")
                if msg_type == "kicked":
                    log.info("railway", "Kicked by server (new daemon connected)")
                    close_info = "kicked"
                    break
                if msg_type in self._handlers:
                    if msg_type in self._inline_handlers:
                        # Latency-sensitive handlers (eg. proxy_request) can run directly on WS thread.
                        try:
                            self._handlers[msg_type](data)
                        except Exception as e:
                            log.error("railway", f"Inline handler error for {msg_type}: {e}")
                    else:
                        # Enqueue for main thread processing
                        self._work_queue.put((msg_type, data))
                elif msg_type == "slide_log":
                    _event = data.get("event", "")
                    _full_slug = data.get("slug", "")
                    _slug = re.sub(r'-[0-9a-f]{32}$', '', _full_slug)
                    _labels = {
                        "download_slide_request": "pdf download",
                        "download_slide_completed": "✅ pdf downloaded ok",
                        "download_failed": "pdf download failed",
                    }
                    _label = _labels.get(_event, _event)
                    _arrow = "↓" if _event.endswith("_completed") else "↑"
                    log.info("railway", f"{_arrow} {_label}: {_slug}")
                    if _event == "download_slide_completed" and _full_slug:
                        from daemon.misc.state import misc_state
                        from daemon.slides.router import _broadcast_slides_updated
                        from daemon.telemetry.ws_propagation import extract_trace_context
                        _downloaded_at = data.get("downloaded_at") or datetime.now(timezone.utc).isoformat()
                        existing = misc_state.slides_updated.get(_full_slug, {})
                        misc_state.slides_updated[_full_slug] = {**existing, "downloaded_at": _downloaded_at}
                        # Restore the upstream trace context (set by Railway's
                        # _push_log) so the broadcast chains under the same
                        # trace as the originating participant request.
                        _ctx = extract_trace_context(data)
                        if _ctx is not None:
                            from opentelemetry import context as _otel_ctx
                            _token = _otel_ctx.attach(_ctx)
                            try:
                                _broadcast_slides_updated()
                            finally:
                                _otel_ctx.detach(_token)
                        else:
                            _broadcast_slides_updated()
        except ConnectionClosed as e:
            close_info = f"code={e.code} reason={e.reason!r}"
        finally:
            with self._ws_lock:
                self._ws = None
            log.info("railway", f"Disconnected ({close_info})")

    @staticmethod
    def _msg_name(msg: dict) -> str:
        msg_type = str(msg.get("type") or "unknown")
        if msg_type == "broadcast" and isinstance(msg.get("event"), dict):
            event_type = str(msg["event"].get("type") or "unknown")
            return event_type
        return msg_type

    @staticmethod
    def _should_trace_msg(msg: dict) -> bool:
        return str(msg.get("type") or "unknown") not in _NOISY_PROXY_MSG_TYPES
