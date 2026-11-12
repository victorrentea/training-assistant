"""The participant page survives Wi-Fi that changes under it.

12 Nov 2026: several participants sat on a frozen page until they refreshed it by
hand. A network switch kills the socket silently (no FIN, no RST), so 'close' never
fires and the old backoff never started. Pinned here:

- a socket silent past the heartbeat window is replaced (only once heartbeats were seen);
- going offline shows the corner card at once, coming back online replaces the socket;
- when the relay keeps refusing, the card offers Reconnect, and hides once live again.

The real participant.html is served through Playwright routing with the API and the
WebSocket mocked, so no server or daemon is involved.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SID = "abc123"
ORIGIN = "http://localhost:59999"  # a secure context (crypto.randomUUID); never actually contacted
HEARTBEAT = json.dumps({"type": "heartbeat"})
CARD_SHOWN = "() => document.getElementById('offline-card').classList.contains('show')"
CARD_TITLE = "() => document.getElementById('offline-card-title').textContent"


def _state() -> dict:
    return {
        "mode": "workshop", "my_score": 0, "my_score_token": "t", "my_name": "Alice",
        "my_avatar": "", "current_activity": "none", "session_name": "2026-11-12 Test",
        "participant_names": ["Alice"], "wordcloud": {"words": {}, "word_order": [], "topic": ""},
        "qa_questions": [], "quiz": None, "quiz_active": False, "poll": None, "poll_active": False,
        "codereview": {}, "debate": {}, "emoji_counters": {}, "slides_current": None,
        "slides_history_count": 0, "files_count": 0, "prompts_count": 0, "emoji_catalog": [],
    }


class _Participant:
    def __init__(self, browser):
        self.sockets = []
        self.refuse = False  # True: every new socket is closed right away (relay down)
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        self.ctx.route("**/*", self._handle)
        self.ctx.route_web_socket("ws://localhost:59999/ws/**", self._on_socket)
        self.page = self.ctx.new_page()

    def _on_socket(self, ws):
        self.sockets.append(ws)
        if self.refuse:
            ws.close(code=1011)
        else:
            ws.send(HEARTBEAT)  # the relay's first frame makes the socket live

    def _handle(self, route):
        url = route.request.url
        if not url.startswith(ORIGIN):
            return route.continue_()
        path = url[len(ORIGIN):].split("?")[0]
        if path.startswith("/static/"):
            f = REPO / path.lstrip("/")
            if not f.exists():
                return route.fulfill(status=404, body="")
            ct = "text/css" if f.suffix == ".css" else "application/javascript"
            return route.fulfill(body=f.read_bytes(), content_type=ct)
        if path in (f"/{SID}", f"/{SID}/"):
            return route.fulfill(body=(REPO / "static" / "participant.html").read_bytes(), content_type="text/html")
        if path == f"/{SID}/api/participant/state":
            return route.fulfill(json=_state())
        if path == f"/{SID}/api/participant/register":
            return route.fulfill(json={"name": "Alice", "avatar": "", "name_conflict": False})
        return route.fulfill(json={})

    def open(self):
        self.page.goto(f"{ORIGIN}/{SID}?as=Alice")
        self.page.wait_for_function("() => typeof _firstConnect !== 'undefined' && !_firstConnect", timeout=15000)
        assert len(self.sockets) == 1

    def wait_sockets(self, n, timeout=5000):
        for _ in range(timeout // 100):
            if len(self.sockets) >= n:
                break
            self.page.wait_for_timeout(100)  # also pumps the Playwright event loop
        assert len(self.sockets) >= n, f"expected {n} sockets, got {len(self.sockets)}"

    def close(self):
        self.ctx.close()


@pytest.fixture()
def participant(browser):
    made = []

    def make():
        made.append(_Participant(browser))
        return made[-1]

    yield make
    for p in made:
        p.close()


def test_silent_socket_is_replaced_once_heartbeats_were_seen(participant):
    pax = participant()
    pax.open()
    pax.page.wait_for_function("() => _wsHeartbeatSeen")

    # The network switched: the socket stays "open" but nothing arrives any more.
    pax.page.evaluate("() => { _wsLastFrameAt = Date.now() - 61000; _abandonSocketIfSilent(_WS_SILENCE_MS); }")

    pax.wait_sockets(2)
    assert not pax.page.evaluate(CARD_SHOWN), "a quick swap must not flash the offline card"


def test_silence_without_heartbeats_never_churns(participant):
    pax = participant()
    pax.open()
    pax.page.evaluate("() => { _wsHeartbeatSeen = false; _wsLastFrameAt = Date.now() - 61000;"
                      " _abandonSocketIfSilent(_WS_SILENCE_MS); }")
    pax.page.wait_for_timeout(1000)
    assert len(pax.sockets) == 1


def test_wifi_switch_shows_card_then_reconnects_on_online(participant):
    pax = participant()
    pax.open()

    pax.page.evaluate("() => window.dispatchEvent(new Event('offline'))")
    assert pax.page.evaluate(CARD_SHOWN)

    # Back on a (different) network: the old socket is not trusted, a new one opens.
    pax.page.evaluate("() => window.dispatchEvent(new Event('online'))")
    pax.wait_sockets(2)
    pax.page.wait_for_function(f"() => ({CARD_TITLE})() === 'Back online'", timeout=5000)
    pax.page.wait_for_function(f"() => !({CARD_SHOWN})()", timeout=5000)


def test_relay_down_offers_reconnect_button(participant):
    pax = participant()
    pax.open()
    pax.refuse = True
    # Skip the quick retries (~12 s) so the next failure counts as "exhausted".
    pax.page.evaluate("() => { _wsReconnectAttempts = _WS_RECONNECT_DELAYS.length; _ws.close(); }")
    pax.page.wait_for_function(CARD_SHOWN, timeout=5000)
    assert pax.page.evaluate(CARD_TITLE) == "Connection lost"
    btn = pax.page.locator("#offline-card-btn")
    assert btn.is_visible() and btn.is_enabled()

    # The relay is back; the participant does not wait for the 3-5 s backoff.
    pax.refuse = False
    before = len(pax.sockets)
    btn.click()
    pax.wait_sockets(before + 1, timeout=1500)
    pax.page.wait_for_function(f"() => !({CARD_SHOWN})()", timeout=5000)
