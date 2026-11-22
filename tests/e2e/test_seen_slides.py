""""Seen slides" in the participant sidebar: the session's deck of every slide shown
(daemon/slides/seen_slides.py) opens in the Slides viewer at its last page, and new
pages arrive live without pulling back a reader who scrolled away.

The real participant.html is served through Playwright routing with the API and the
WebSocket mocked, so no server or daemon is involved.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "docker"))
from generate_fixture_pdfs import _minimal_pdf  # noqa: E402

SID = "abc123"
SEEN = "seen-slides-abc123"
ORIGIN = "http://localhost:59999"
PAGE_INFO = "() => (document.getElementById('pdf-page-info') || {}).textContent"


def _state(seen_count: int) -> dict:
    return {
        "mode": "workshop", "my_score": 0, "my_score_token": "t", "my_name": "Alice",
        "my_avatar": "", "current_activity": "none", "session_name": "2026-11-22 Test",
        "participant_names": ["Alice"], "wordcloud": {"words": {}, "word_order": [], "topic": ""},
        "qa_questions": [], "quiz": None, "quiz_active": False, "poll": None, "poll_active": False,
        "codereview": {}, "debate": {}, "emoji_counters": {},
        "slides_current": {"slug": "deck", "page": 2},
        "slides_seen": {"slug": SEEN, "count": seen_count, "updated_at": f"v{seen_count}"},
        "files_count": 0, "prompts_count": 0, "emoji_catalog": [],
    }


class _Participant:
    def __init__(self, browser, seen_count: int, slow_deck: bool = False):
        self.seen_count = seen_count
        self.slow_deck = slow_deck
        self.sockets = []
        self.downloads: list[str] = []
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        self.ctx.route("**/*", self._handle)
        self.ctx.route_web_socket("ws://localhost:59999/ws/**", lambda ws: self.sockets.append(ws))
        self.page = self.ctx.new_page()

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
        if path in (f"/{SID}", f"/{SID}/", f"/{SID}/past-slides"):
            return route.fulfill(body=(REPO / "static" / "participant.html").read_bytes(), content_type="text/html")
        if path == f"/{SID}/api/participant/state":
            return route.fulfill(json=_state(self.seen_count))
        if path == f"/{SID}/api/participant/register":
            return route.fulfill(json={"name": "Alice", "avatar": "", "name_conflict": False})
        if path == f"/{SID}/api/slides":
            return route.fulfill(json={"slides": [
                {"name": "Deck", "slug": "deck", "url": f"/{SID}/api/slides/download/deck", "status": "cached"},
            ]})
        if path == f"/{SID}/api/slides/download/{SEEN}":
            self.downloads.append(SEEN)
            return route.fulfill(body=_minimal_pdf(self.seen_count, "Seen"), content_type="application/pdf")
        if path.startswith(f"/{SID}/api/slides/download/"):
            if self.slow_deck:  # the trainer's real deck is ~8 MB: it arrives last
                time.sleep(1.5)
            return route.fulfill(body=_minimal_pdf(20, "Deck"), content_type="application/pdf")
        if path.startswith(f"/{SID}/api/slides/check/"):
            return route.fulfill(json={"status": "cached"})
        return route.fulfill(json={})

    def trainer_shows_one_more(self):
        self.seen_count += 1
        msg = json.dumps({"type": "slides_seen_updated", "slug": SEEN, "count": self.seen_count,
                          "updated_at": f"v{self.seen_count}"})
        for ws in self.sockets:
            ws.send(msg)

    def wait_page(self, text: str):
        self.page.wait_for_function(f"{PAGE_INFO} === '{text}'", timeout=15000)

    def close(self):
        self.ctx.close()


@pytest.fixture()
def participant(browser):
    made = []

    def make(**kwargs):
        made.append(_Participant(browser, **kwargs))
        return made[-1]

    yield make
    for p in made:
        p.close()


def test_seen_slides_open_at_the_last_page_and_grow_live(participant):
    pax = participant(seen_count=3)
    pax.page.goto(f"{ORIGIN}/{SID}?as=Alice")
    pax.page.wait_for_function("() => typeof window.loadPdf === 'function'", timeout=15000)
    pax.page.wait_for_function("() => document.getElementById('seen-slides-badge').textContent === '3'", timeout=15000)

    pax.page.locator("#seen-slides-nav").click()

    pax.page.wait_for_function(f"() => window.Slides && window.Slides.front.slug === '{SEEN}'", timeout=15000)
    pax.wait_page("3 / 3")
    assert pax.page.evaluate("() => document.getElementById('slides-follow-checkbox').checked") is False
    assert "nav-active" in pax.page.locator("#seen-slides-nav").get_attribute("class")
    assert pax.page.evaluate("() => location.pathname") == f"/{SID}/past-slides"

    # On the last page: the new slide comes on screen.
    pax.trainer_shows_one_more()
    pax.wait_page("4 / 4")
    assert pax.page.locator("#seen-slides-badge").inner_text() == "4"
    if os.environ.get("SEEN_SLIDES_SCREENSHOT"):
        pax.page.screenshot(path=os.environ["SEEN_SLIDES_SCREENSHOT"])

    # Scrolled back to the first page: a new slide does not pull the reader away.
    pax.page.evaluate("() => _scrollSlidesToPage(1, { instant: true })")
    pax.wait_page("1 / 4")
    pax.trainer_shows_one_more()
    pax.page.wait_for_function(f"{PAGE_INFO}.endsWith('/ 5')", timeout=15000)
    pax.page.wait_for_timeout(300)
    assert pax.page.evaluate(PAGE_INFO) == "1 / 5"


def test_without_slides_shown_the_entry_says_so(participant):
    pax = participant(seen_count=0)
    pax.page.goto(f"{ORIGIN}/{SID}?as=Alice")
    pax.page.wait_for_function("() => typeof window.loadPdf === 'function' && typeof _seenSlides !== 'undefined'"
                               " && !!_seenSlides", timeout=15000)
    assert not pax.page.locator("#seen-slides-badge").is_visible()

    pax.page.locator("#seen-slides-nav").click()

    assert pax.downloads == []


def test_the_past_slides_link_opens_the_seen_deck_not_the_trainers(participant):
    """A first visit follows the trainer by default; landing on /past-slides must not let
    his deck load and swap in over the seen one."""
    pax = participant(seen_count=3, slow_deck=True)
    pax.page.goto(f"{ORIGIN}/{SID}/past-slides?as=Alice")

    pax.page.wait_for_function(f"() => window.Slides && window.Slides.front.slug === '{SEEN}'", timeout=15000)
    pax.wait_page("3 / 3")
    pax.page.wait_for_timeout(1500)  # no late swap to the trainer's deck
    assert pax.page.evaluate("() => window.Slides.front.slug") == SEEN
    assert pax.page.evaluate("() => location.pathname") == f"/{SID}/past-slides"
