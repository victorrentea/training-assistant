"""WS client connecting to the local addons WebSocket server (wispr-flow/ws_server.py).

The addons server runs at ws://127.0.0.1:<WS_SERVER_PORT> (default 8765).

Protocol:
  Daemon → Addons: {"type": "fx_fired", "caller": "<display name>", "anonymous": <bool>}
              — someone holding the secret FX link pressed it; the overlay names them
                on a bottom-center tab. No tile: it is already playing out loud.
                "caller" is a resolved display name, never a UUID (see FxFiredMsg
                in ws_messages.py).
  Daemon → Addons: {"type": "display_emoji", "emoji": "<char>", "count": 1, "glow": "#rrggbb"?}
              — relayed by addons to the desktop overlay for animation. "glow" is
              an optional per-participant halo colour (omitted → no halo).
  Addons → Daemon: {"type": "slide_presenting_now", "deck": "<name>", "slide": <n>, "presenting": <bool>}
              — pushed on every PowerPoint slide/deck change (no message when unchanged),
                and once more with "frontmost": true when PowerPoint comes to the front
                (talk phones switch from the trainer's notes back to the slides)
  Addons → Daemon: {"type": "slide_seen", "phase": "qualified"|"closed", "path": "<abs .pptx>",
                    "deck": "<name>", "slide_id": <n>, "slide": <n>, "at": "<ISO 8601>"}
              — a slide stayed 7 s with PowerPoint in front (qualified), or was left (closed);
                the deck is saved on disk by then (daemon/slides/seen_slides.py)
  Daemon → Addons: {"type": "slide_seen_captured", "deck": "<name>", "slide": <n>, "change": "added"|"updated"}
              — the session's seen deck took a new slide or a new version of one: a brief
                toast on the trainer's screen, so a capture outside class hours is noticed
  Addons → Daemon: {"type": "slides_viewed", "slides": [{"fileName": "<name>", "page": <n>, "seconds": <n>}, ...]}
              — periodic (60s) delta of per-slide viewing durations
  On connect:  server immediately sends the last known slide state as a welcome message.
"""
import concurrent.futures
import json
import os
import queue
import threading
from typing import Any, Callable

from daemon import log

_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))
_RECONNECT_INTERVAL = 5.0  # seconds between reconnect attempts
_OPEN_TIMEOUT = 5.0
_NAME = "addons   "


# One recorder thread: a GitHub lookup in `record_file_opened` takes seconds, and
# on the receive loop it would hold back the next `git_file_check` past the
# Mac's 5 s wait. One worker keeps the load-modify-save of opened-files.md serial.
_RECORDER = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="git-file-record")


def _handle_git_file_opened(data: dict) -> None:
    from daemon import files_md
    url = data.get("url", "")
    branch = data.get("branch", "") or ""
    file_path = data.get("file", "")
    if not url or not file_path:
        return
    files_md.record_file_opened(url, branch, file_path)
    log.debug(_NAME, f"← git {url.split('/')[-1]}@{branch or '?'} {file_path}")


def _git_file_check_result(data: dict) -> dict:
    """Answer the Mac's `git_file_check`: would this file reach the session's
    opened-files list? Only then does the Mac offer its pill (and send)."""
    from daemon import files_md
    try:
        listed = files_md.would_record(data.get("url", "") or "", data.get("file", "") or "")
    except Exception:
        listed = False
    return {"type": "git_file_check_result", "id": data.get("id", ""), "listed": listed}


def _session_started_msg(
    participant_url: str, session_folder: str | None, show_join_link: bool = False
) -> dict:
    """The ``session_started`` payload, dates included.

    ``show_join_link`` asks the addons to put the join link and its QR on the
    screen right away. Set only when the trainer has just started the session:
    the same message is re-sent on every daemon restart and addons reconnect,
    and those must not raise a banner over whatever is being projected.

    ``session_last_day`` is the last day of the set the folder name declares
    ("2026-09-14..15 AI@X" -> "2026-09-15"). The addons use it to hold the
    feedback-form offer back until then: a survey handed out on day 1 of 3 asks
    about a third of a workshop. The daemon is the one that knows the set,
    because it is the one that parses session folder names.

    Omitted when the folder carries no parsable dates, which the addons read as
    "offer anyway" rather than "never offer".
    """
    msg: dict = {"type": "session_started", "participant_url": participant_url}
    if show_join_link:
        msg["show_join_link"] = True
    if not session_folder:
        return msg
    msg["session_folder"] = session_folder
    from pathlib import Path

    from daemon.config import parse_session_folder_dates
    try:
        dates = parse_session_folder_dates(Path(session_folder).name)
    except ValueError as e:
        log.error(_NAME, f"Invalid dates in session folder {session_folder!r}: {e}")
        return msg
    if dates is not None:
        msg["session_last_day"] = dates.end.isoformat()
    return msg


class AddonBridgeClient:
    def __init__(self):
        self._ws = None
        self._ws_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._slide_queue: queue.Queue = queue.Queue()
        # Set on every slide event, so the main loop wakes at once instead of
        # finishing its poll-interval sleep: phones follow a slide change in
        # milliseconds, not up to a second later.
        self.slide_wakeup = threading.Event()
        self._slides_viewed_queue: queue.Queue = queue.Queue()
        self._on_connection_change: Callable[..., Any] | None = None

    # ── Public API (callable from any thread) ─────────────────────────────────

    @property
    def connected(self) -> bool:
        with self._ws_lock:
            return self._ws is not None

    def set_on_connection_change(self, callback: Callable[..., Any]) -> None:
        """callback(connected: bool) — called from WS thread on state change."""
        self._on_connection_change = callback

    def send_emoji(self, emoji: str, glow: str | None = None) -> bool:
        """Forward an emoji reaction to the overlay. Best-effort; never raises.

        glow: optional ``#rrggbb`` halo colour identifying the sender; omitted
        from the payload when None so older overlays are unaffected.
        """
        msg: dict = {"type": "display_emoji", "emoji": emoji, "count": 1}
        if glow:
            msg["glow"] = glow
        return self._send(msg)

    def send_bell(self, caller_name: str, anonymous: bool = False) -> bool:
        """Forward an attention bell to the overlay. Best-effort; never raises.

        Emits ``{"type":"bell_ring","caller":"<name>","anonymous":<bool>}`` — the
        shared wire contract the merged Swift receiver reads (``type``+``caller``
        unchanged; ``anonymous`` is the new optional field the Swift side treats
        as defaulting to false). Returns True if sent, False when the bridge is
        disconnected (caller logs the drop).
        """
        msg = {"type": "bell_ring", "caller": caller_name, "anonymous": anonymous}
        return self._send(msg)

    def send_session_started(
        self,
        participant_url: str,
        session_folder: str | None = None,
        show_join_link: bool = False,
    ) -> bool:
        """Notify addons that a session has started with the participant join URL.

        session_folder: absolute path to the active session folder; addons use it to
        save artefacts (e.g. screenshots) into the session.
        show_join_link: also raise the join link + QR on screen (a session just started).
        """
        return self._send(_session_started_msg(participant_url, session_folder, show_join_link))

    def send_session_ended(self) -> bool:
        """Notify addons that the session has ended."""
        msg = {"type": "session_ended"}
        sent = self._send(msg)
        if sent:
            log.info(_NAME, "→ ended session")
        return sent

    def send_fx_fired(self, caller: str = "Someone", anonymous: bool = False) -> bool:
        """Name whoever pressed the secret FX link, on the trainer's desktop.

        Best-effort, like everything else here. The press itself already fires
        the tile's sound and paired visual through the *other* edge to the Mac
        (`effects_client`, HTTP on :55123) — which is exactly why the tile is
        not on this wire: the room can hear it. Who pressed it is the one thing
        the room cannot tell the trainer, so it is the only thing sent.

        `caller` is a resolved display name — the daemon never puts a UUID on
        this wire (see `fx_fire`).
        """
        msg = {"type": "fx_fired", "caller": caller, "anonymous": anonymous}
        return self._send(msg)

    def send_paste_received(self, sender: str, text: str) -> bool:
        """A participant sent text from the Participant View: Victor Mac raises a
        bottom-left pill with a Copy button that stays until Victor dismisses it,
        so the text reaches his clipboard without opening the host panel.

        `sender` is a resolved display name, never a UUID.
        """
        return self._send({"type": "paste_received", "sender": sender, "text": text})

    def send_slide_seen_captured(self, deck: str, slide: int, change: str) -> bool:
        """The session's seen deck changed: Victor Mac shows a passing toast."""
        sent = self._send({"type": "slide_seen_captured", "deck": deck, "slide": slide, "change": change})
        if sent:
            log.info(_NAME, f"→ slide_seen_captured: {deck} #{slide} {change}")
        return sent

    def send_pdf_export_alarm(self, deck: str, slug: str, failing: bool, detail: str = "") -> bool:
        """Raise (failing=True) or clear (failing=False) the macOS 'PDF export
        failing' alarm for a deck. Best-effort; never raises.

        The addon shows a persistent native notification while failing=True and
        removes it on failing=False (export recovered).
        """
        msg = {
            "type": "pdf_export_alarm",
            "deck": deck,
            "slug": slug,
            "failing": failing,
            "detail": detail,
        }
        sent = self._send(msg)
        if sent:
            arrow = "🚨 raise" if failing else "✅ clear"
            log.info(_NAME, f"→ pdf_export_alarm {arrow} deck={deck!r}")
        return sent

    def drain_slides(self) -> list[dict]:
        """Return all pending slide events. Call from the main thread each loop."""
        events: list[dict] = []
        while True:
            try:
                events.append(self._slide_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def drain_slides_viewed(self) -> list[list[dict]]:
        """Return all pending slides_viewed batches. Call from the main thread each loop."""
        batches: list[list[dict]] = []
        while True:
            try:
                batches.append(self._slides_viewed_queue.get_nowait())
            except queue.Empty:
                break
        return batches

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
        try:
            from daemon.telemetry.ws_propagation import inject_trace_context
            inject_trace_context(msg)
        except ImportError:
            pass
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
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect as ws_connect

        url = f"ws://127.0.0.1:{_PORT}"
        try:
            ws = ws_connect(url, open_timeout=_OPEN_TIMEOUT)
        except Exception:
            # Bridge not running yet — silent retry
            return

        with self._ws_lock:
            self._ws = ws
        log.info(_NAME, f"→ connected {url}")
        self._fire_connection_change(True)

        try:
            for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                # Extract trace context from addons messages
                _ctx = None
                _token = None
                try:
                    from daemon.telemetry.ws_propagation import extract_trace_context
                    _ctx = extract_trace_context(data)
                    if _ctx:
                        from opentelemetry import context
                        _token = context.attach(_ctx)
                except ImportError:
                    pass
                if data.get("type") == "slide_presenting_now":
                    self._slide_queue.put(data)
                    self.slide_wakeup.set()
                elif data.get("type") == "slide_seen":
                    from daemon.slides import seen_slides
                    seen_slides.submit(data)
                elif data.get("type") == "slides_viewed":
                    slides = data.get("slides", [])
                    if slides:
                        self._slides_viewed_queue.put(slides)
                elif data.get("type") == "git_file_opened":
                    _RECORDER.submit(_handle_git_file_opened, data)
                elif data.get("type") == "git_file_check":
                    # A GitHub lookup may be slow: answer off the receive loop.
                    threading.Thread(
                        target=lambda d=data: self._send(_git_file_check_result(d)),
                        name="git-file-check", daemon=True,
                    ).start()
                if _ctx and _token:
                    context.detach(_token)
        except ConnectionClosed:
            pass
        finally:
            with self._ws_lock:
                self._ws = None
            log.info(_NAME, "ws disconnected")
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


def send_emoji(emoji: str, glow: str | None = None) -> bool:
    """Best-effort emoji send to addons overlay. Returns True if sent.

    glow: optional ``#rrggbb`` per-participant halo colour.
    """
    return _client is not None and _client.send_emoji(emoji, glow)


def send_bell(caller_name: str, anonymous: bool = False) -> bool:
    """Best-effort bell_ring send to addons overlay. Returns True if sent."""
    return _client is not None and _client.send_bell(caller_name, anonymous)


def send_session_started(
    participant_url: str, session_folder: str | None = None, show_join_link: bool = False
) -> bool:
    """Best-effort session_started message to addons. Returns True if sent."""
    return _client is not None and _client.send_session_started(
        participant_url, session_folder, show_join_link
    )


def send_session_ended() -> bool:
    """Best-effort session_ended message to addons. Returns True if sent."""
    return _client is not None and _client.send_session_ended()


def send_paste_received(sender: str, text: str) -> bool:
    """Best-effort paste_received message to addons. Returns True if sent."""
    return _client is not None and _client.send_paste_received(sender, text)


def send_slide_seen_captured(deck: str, slide: int, change: str) -> bool:
    """Best-effort slide_seen_captured message to addons. Returns True if sent."""
    return _client is not None and _client.send_slide_seen_captured(deck, slide, change)


def send_pdf_export_alarm(deck: str, slug: str, failing: bool, detail: str = "") -> bool:
    """Best-effort pdf_export_alarm message to addons. Returns True if sent."""
    return _client is not None and _client.send_pdf_export_alarm(deck, slug, failing, detail)


def send_fx_fired(caller: str = "Someone", anonymous: bool = False) -> bool:
    """Best-effort fx_fired message to addons. Returns True if sent."""
    return _client is not None and _client.send_fx_fired(caller, anonymous)
