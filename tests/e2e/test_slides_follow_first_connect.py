"""Regression: a participant who connects with Follow ticked lands on the trainer's
current slide right away — no need for the trainer to change slide first.

Two ways it used to fail, each pinned by one test:

1. pdf.js is a CDN module that runs only after the page has parsed. When the boot
   sequence reached selectTopic() before it (cold cache, name gate skipped),
   window.loadPdf was undefined: the deck was marked active but never loaded, and
   later same-deck slide changes only tried to scroll sections that did not exist.
2. The first load scrolled to the host's page only after EVERY page had rendered.
   On a big deck the participant sat on slide 1 for seconds, and a slide change
   during the render was undone by the late jump back to the starting page.

Pages are now drawn lazily: every page gets a placeholder of its own size at once,
and only the ones around the viewport hold a drawn canvas (drawing all of a
100-slide deck held ~500 MB of canvas per tab). The last test pins that.

The real participant.html is served through Playwright routing with the API and the
WebSocket mocked, so no server or daemon is involved.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "docker"))
from generate_fixture_pdfs import _minimal_pdf  # noqa: E402

SID = "abc123"
ORIGIN = "http://localhost:59999"  # a secure context (crypto.randomUUID); never actually contacted
PAGE_INFO = "() => (document.getElementById('pdf-page-info') || {}).textContent"
# Page n is drawn: its canvas has a bitmap and its text layer is in place.
DRAWN = """n => { const s = document.querySelector('#pdf-pages section[data-page="' + n + '"]');
  return !!s && s.querySelector('canvas').width > 0 && !!s.querySelector('.textLayer'); }"""
DRAWN_COUNT = "() => [...document.querySelectorAll('#pdf-stack canvas')].filter(c => c.width > 0).length"
SECTION_COUNT = "() => document.querySelectorAll('#pdf-pages section').length"


def _state(host_page: int) -> dict:
    return {
        "mode": "workshop", "my_score": 0, "my_score_token": "t", "my_name": "Alice",
        "my_avatar": "", "current_activity": "none", "session_name": "2026-09-25 Test",
        "participant_names": ["Alice"], "wordcloud": {"words": {}, "word_order": [], "topic": ""},
        "qa_questions": [], "quiz": None, "quiz_active": False, "poll": None, "poll_active": False,
        "codereview": {}, "debate": {}, "emoji_counters": {},
        "slides_current": {"slug": "deck", "page": host_page},
        "slides_history_count": 0, "files_count": 0, "prompts_count": 0, "emoji_catalog": [],
    }


class _MockedParticipant:
    """Serves static/participant.html with every backend call answered locally."""

    def __init__(self, browser, pages: int, host_page: int, hold_pdfjs: bool = False):
        self.pdf = _minimal_pdf(pages, "Deck")
        self.host_page = host_page
        self.hold_pdfjs = hold_pdfjs
        self.held_pdfjs = []
        self.sockets = []
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        self.ctx.route("**/*", self._handle)
        self.ctx.route_web_socket("ws://localhost:59999/ws/**", lambda ws: self.sockets.append(ws))
        self.page = self.ctx.new_page()

    def _handle(self, route):
        url = route.request.url
        if self.hold_pdfjs and url.endswith("/pdf.min.mjs"):
            self.held_pdfjs.append(route)  # released by release_pdfjs()
            return
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
            return route.fulfill(json=_state(self.host_page))
        if path == f"/{SID}/api/participant/register":
            return route.fulfill(json={"name": "Alice", "avatar": "", "name_conflict": False})
        if path == f"/{SID}/api/slides":
            return route.fulfill(json={"slides": [
                {"name": "Deck", "slug": "deck", "url": f"/{SID}/api/slides/download/deck", "status": "cached"},
            ]})
        if path.startswith(f"/{SID}/api/slides/download/"):
            return route.fulfill(body=self.pdf, content_type="application/pdf")
        return route.fulfill(json={})

    def release_pdfjs(self):
        for route in self.held_pdfjs:
            route.fulfill(response=route.fetch())
        self.held_pdfjs.clear()

    def host_moves_to(self, page: int):
        msg = json.dumps({"type": "current_slide_updated", "current_slide": {"slug": "deck", "page": page}})
        for ws in self.sockets:
            ws.send(msg)

    def wait_deck_mounted(self, pages: int):
        """Every page has its placeholder section — drawn or not."""
        self.page.wait_for_function(
            "n => window.Slides && window.Slides.front.slug === 'deck'"
            " && document.querySelectorAll('#pdf-pages section').length >= n",
            arg=pages, timeout=30000)

    def close(self):
        self.ctx.close()


@pytest.fixture()
def participant(browser):
    made = []

    def make(**kwargs):
        made.append(_MockedParticipant(browser, **kwargs))
        return made[-1]

    yield make
    for p in made:
        p.close()


def test_deck_opens_on_host_slide_when_pdfjs_loads_after_boot(participant):
    pax = participant(pages=30, host_page=17, hold_pdfjs=True)
    # ?as= skips the name gate, like a rejoin. "commit": the page's load event waits
    # for the held module script.
    pax.page.goto(f"{ORIGIN}/{SID}?as=Alice", wait_until="commit")
    # Boot has already picked the host's deck while pdf.js is still in flight.
    pax.page.wait_for_function("() => typeof _activeSlideId !== 'undefined' && !!_activeSlideId", timeout=15000)
    assert pax.held_pdfjs, "pdf.js request was not held back"

    pax.release_pdfjs()

    pax.wait_deck_mounted(30)
    pax.page.wait_for_function(f"{PAGE_INFO} === '17 / 30'", timeout=10000)
    pax.page.wait_for_function(DRAWN, arg=17, timeout=10000)


def test_big_deck_lands_on_host_slide_at_once_and_keeps_up(participant):
    pages, host_page, next_page = 150, 40, 120
    pax = participant(pages=pages, host_page=host_page)
    # Through the name gate, with pdf.js already loaded: only the drawing order is on trial.
    pax.page.goto(f"{ORIGIN}/{SID}")
    pax.page.wait_for_function("() => typeof window.loadPdf === 'function'", timeout=15000)
    pax.page.locator("#name-gate-anon").click()

    # The host's slide is drawn and on screen without the 39 slides before it being drawn.
    pax.page.wait_for_function(DRAWN, arg=host_page, timeout=30000)
    assert pax.page.evaluate(PAGE_INFO) == f"{host_page} / {pages}"
    assert pax.page.evaluate(SECTION_COUNT) == pages  # every page has its place...
    assert pax.page.evaluate(DRAWN_COUNT) <= 12       # ...only the ones around the viewport are drawn
    assert not pax.page.evaluate(DRAWN, 1)

    # The host moves to a slide far away, never drawn so far.
    pax.host_moves_to(next_page)

    pax.page.wait_for_function(f"{PAGE_INFO} === '{next_page} / {pages}'", timeout=10000)
    pax.page.wait_for_function(DRAWN, arg=next_page, timeout=10000)
    pax.page.wait_for_timeout(500)  # no late jump back to the starting page
    assert pax.page.evaluate(PAGE_INFO) == f"{next_page} / {pages}"


def test_scrolling_through_the_deck_draws_every_page_but_holds_only_a_few(participant):
    pages = 60
    pax = participant(pages=pages, host_page=1)
    pax.page.goto(f"{ORIGIN}/{SID}?as=Alice")
    pax.page.wait_for_function(DRAWN, arg=1, timeout=30000)
    pax.wait_deck_mounted(pages)

    # Sample every frame: which pages have been seen drawn, and how many at once.
    pax.page.evaluate("""() => { window.__seen = new Set(); window.__peak = 0;
      (function watch() { let live = 0;
        document.querySelectorAll('#pdf-pages section[data-page]').forEach(s => {
          if (s.querySelector('canvas').width > 0) { live++; if (s.querySelector('.textLayer')) window.__seen.add(Number(s.dataset.page)); } });
        window.__peak = Math.max(window.__peak, live); requestAnimationFrame(watch); })(); }""")
    for n in range(1, pages + 1):
        pax.page.evaluate("""n => { const el = document.getElementById('pdf-pages');
          el.style.scrollBehavior = 'auto'; el.scrollTop = el.querySelector('section[data-page="' + n + '"]').offsetTop; }""", n)
        pax.page.wait_for_function(DRAWN, arg=n, timeout=10000)
        pax.page.wait_for_function(f"{PAGE_INFO} === '{n} / {pages}'", timeout=5000)
    pax.page.wait_for_timeout(200)

    assert pax.page.evaluate("() => window.__seen.size") == pages  # nothing is skipped on the way
    assert pax.page.evaluate("() => window.__peak") <= 12          # and the pages left behind are released
    assert not pax.page.evaluate(DRAWN, 1)
    # A released page is a placeholder of the same size: coming back draws it again.
    pax.page.evaluate("() => { document.getElementById('pdf-pages').scrollTop = 0; }")
    pax.page.wait_for_function(DRAWN, arg=1, timeout=10000)
    assert pax.page.evaluate(PAGE_INFO) == f"1 / {pages}"
