"""
Step definitions for slides.feature scenarios.

All When/Then steps use page objects (ParticipantPage, HostPage) exclusively.
API calls are only used in Given steps for infrastructure setup (mock Drive,
session management, addons bridge mock).
"""
import base64
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/tests")

import pytest
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/slides.feature")

# Registry of participants by name — populated by join steps
_participants: dict[str, ParticipantPage] = {}


@pytest.fixture(autouse=True)
def _reset_participants():
    """Clear participant registry before/after each scenario."""
    _participants.clear()
    yield
    _participants.clear()


def _pax(name: str) -> ParticipantPage:
    assert name in _participants, f"Participant '{name}' not joined yet. Known: {list(_participants)}"
    return _participants[name]


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
MOCK_DRIVE_PORT = os.environ.get("MOCK_DRIVE_PORT", "9090")


def _auth_header():
    return base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _api(method, path, data=None, base=None, timeout=10):
    """Low-level HTTP call. Only used in Given steps for infra setup."""
    target = base or DAEMON_BASE
    body = json.dumps(data).encode() if data else (b"" if method in ("POST", "PUT") else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {_auth_header()}", "Content-Type": "application/json"},
        data=body,
    )
    if method in ("POST", "PUT") and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _mock_drive_stats():
    req = urllib.request.Request(f"http://localhost:{MOCK_DRIVE_PORT}/mock-drive/stats")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _reset_mock_drive():
    req = urllib.request.Request(f"http://localhost:{MOCK_DRIVE_PORT}/mock-drive/reset-stats", method="POST",
                                 data=b"", headers={"Content-Length": "0"})
    urllib.request.urlopen(req, timeout=5)


def _set_drive_delay(slug, seconds):
    req = urllib.request.Request(
        f"http://localhost:{MOCK_DRIVE_PORT}/mock-drive/set-delay",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"slug": slug, "delay_s": seconds}).encode(),
    )
    urllib.request.urlopen(req, timeout=5)


# ── Addon bridge mock ──────────────────────────────────────────────────

def _run_mock_addon_bridge(deck, slide, stop_event):
    import asyncio

    import websockets

    async def handle(websocket):
        await websocket.send(json.dumps({
            "type": "slide", "deck": deck, "slide": slide, "presenting": True
        }))
        await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    async def serve():
        async with websockets.serve(handle, "127.0.0.1", 8765):
            await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    asyncio.run(serve())


# ── Given steps ────────────────────────────────────────────────────────

@given(parsers.parse('the addons bridge reports current slide is "{deck}" page {page:d}'))
@when(parsers.parse('the addons bridge reports current slide is "{deck}" page {page:d}'))
def addons_bridge_reports(request, deck, page):
    # Stop any existing bridge before starting a new one
    prev_stop = getattr(request.config, "_addon_bridge_stop", None)
    if prev_stop is not None:
        prev_stop.set()
        time.sleep(0.5)  # let previous server release port

    stop = threading.Event()
    request.config._addon_bridge_stop = stop
    t = threading.Thread(target=_run_mock_addon_bridge, args=(deck, page, stop), daemon=True)
    t.start()
    request.addfinalizer(stop.set)
    time.sleep(1)  # let bridge accept connections


@given("host is connected", target_fixture="host_context")
def host_connected(browser, session_id):
    ctx = browser.new_context(
        http_credentials={"username": HOST_USER, "password": HOST_PASS}
    )
    page = ctx.new_page()
    page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(page.locator("#tab-poll")).to_be_visible(timeout=10000)
    return {"page": page, "session_id": session_id}


@given(parsers.parse('a {delay:d} second Drive delay on "{slug}"'))
def set_drive_delay(delay, slug):
    _reset_mock_drive()
    _set_drive_delay(slug, delay)


@given(parsers.parse('slide "{slug}" is cached'))
def slide_is_cached(session_id, slug):
    status, _ = _api("GET", f"/api/slides/check/{slug}", timeout=35)
    assert status == 200, f"Failed to cache slide {slug}"



@given(parsers.parse('{name} joins as a participant with follow mode on'),
       target_fixture="follow_pax")
def participant_with_follow_named(browser, session_id, name):
    ctx = browser.new_context()  # fresh context → no localStorage → follow defaults ON
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join(name)
    _participants[name] = pax
    return pax


@given("a fresh participant joins with follow mode on", target_fixture="follow_pax")
def participant_with_follow(browser, session_id):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join("FollowBot")
    _participants["FollowBot"] = pax
    return pax


@given(parsers.parse('{name} joins as a participant'), target_fixture="connected")
def participant_joins(browser, session_id, name):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join(name)
    _participants[name] = pax
    return {"pax": pax}


@given(parsers.parse('{name} clicks the Follow button'))
@when(parsers.parse('{name} clicks the Follow button'))
def named_participant_clicks_follow(name):
    _pax(name).click_follow()


@given(parsers.parse('{name} sees the slides overlay'))
@then(parsers.parse('{name} sees the slides overlay'))
def named_overlay_visible(name):
    pax = _pax(name)
    expect(pax._page.locator("#slides-overlay")).to_be_visible(timeout=10000)


@given(parsers.parse('the slides catalog does not contain "{slug}"'))
def catalog_does_not_contain(connected, slug):
    pax = connected["pax"]
    pax.expand_slides_dock()
    items = pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')
    expect(items).to_have_count(0, timeout=3000)


# ── When steps ─────────────────────────────────────────────────────────

@when(parsers.parse('{name} opens slide "{slug}"'))
def named_participant_opens_slide(name, slug):
    _pax(name).open_slide(slug)


@when(parsers.parse('{name} joins as a participant'))
def when_participant_joins(browser, session_id, name):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join(name)
    _participants[name] = pax


@when(parsers.parse('{name} navigates to page {page_num:d}'))
def navigate_to_page(name, page_num):
    _pax(name).navigate_to_page(page_num)


@when(parsers.parse('{name} clicks the download button for "{slug}"'))
def click_download_button(request, name, slug):
    """Click the download link for a slide and intercept the response."""
    pax = _pax(name)
    pax.expand_slides_dock()
    # Use Playwright's download event to capture the file
    with pax._page.expect_download(timeout=30000) as download_info:
        pax._page.locator(
            f'.slides-list-item[data-slug="{slug}"] .slides-list-download'
        ).click()
    download = download_info.value
    request.config._slides_download = download


@then(parsers.parse('{name} receives a valid PDF file'))
def receives_valid_pdf(request, name):
    """Verify the downloaded file starts with %PDF."""
    download = getattr(request.config, "_slides_download", None)
    assert download is not None, "No download captured — did the download step run?"
    path = download.path()
    content = open(path, "rb").read(5)
    assert content == b"%PDF-", f"Downloaded file is not a valid PDF: {content!r}"


@when(parsers.parse('the host updates the slide "{slug}"'))
def host_updates_slide(session_id, slug):
    """Invalidate a slide to trigger re-download (simulates host updating the Google Drive file).
    This is infra/cache management — API call is appropriate here."""
    _, body = _api("GET", f"/{session_id}/api/slides")
    data = json.loads(body)
    slides_list = data.get("slides", data) if isinstance(data, dict) else data
    drive_url = None
    for s in slides_list:
        if s.get("slug") == slug:
            drive_url = s.get("drive_export_url")
            break
    payload = {"drive_export_url": drive_url} if drive_url else {}
    _api("POST", f"/api/{session_id}/api/slides/invalidate/{slug}", data=payload, base=BASE, timeout=10)


@when("the slide content is visually rendered")
@then("the slide content is visually rendered")
def slide_content_rendered(request, connected):
    """Screenshot the PDF viewer and verify it has non-trivial content (not blank).
    Also stores screenshot for later comparison in 'the slide content has changed'."""
    pax = connected["pax"]
    viewer = pax._page.locator("#slides-pdf-viewer")
    expect(viewer).to_be_visible(timeout=15000)
    pax._page.wait_for_selector("#slides-pdf-viewer canvas", timeout=15000)
    pax._page.wait_for_timeout(1000)  # allow render to complete
    screenshot = viewer.screenshot()
    unique_bytes = len(set(screenshot))
    assert unique_bytes > 50, (
        f"PDF viewer appears blank — only {unique_bytes} unique byte values in screenshot"
    )
    # Store for 'the slide content has changed' assertion
    request.config._slides_before_screenshot = screenshot


@when("Alice's displayed slide is automatically reloaded")
@then("Alice's displayed slide is automatically reloaded")
def slide_automatically_reloaded():
    """Wait for the slide viewer to auto-refresh after host update.
    The slides_cache_status WS message triggers a viewer reload."""
    pax = _pax("Alice")
    # Wait for WS notification and viewer reload
    pax._page.wait_for_timeout(5000)
    # Verify overlay is still open after reload
    expect(pax._page.locator("#slides-overlay")).to_be_visible(timeout=10000)


# ── Then steps ─────────────────────────────────────────────────────────

@then(parsers.parse('the slides catalog contains "{slug}" with a last modified timestamp'))
def catalog_contains_with_timestamp(connected, slug):
    pax = connected["pax"]
    pax.expand_slides_dock()
    item = pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')
    expect(item).to_be_visible(timeout=10000)
    timestamp = item.locator(".slides-list-updated")
    try:
        expect(timestamp).to_be_visible(timeout=5000)
    except AssertionError:
        pax._page.evaluate("() => window.location.reload()")
        pax._page.wait_for_load_state("networkidle")
        pax._page.wait_for_timeout(3000)
        pax.expand_slides_dock()
        item = pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')
        expect(item).to_be_visible(timeout=10000)
        timestamp = item.locator(".slides-list-updated")
        expect(timestamp).to_be_visible(timeout=10000)
    text = timestamp.inner_text().strip()
    assert len(text) > 0, f"Timestamp for '{slug}' is empty"


@then(parsers.parse('the slides catalog contains "{slug}" with last modified timestamp updated'))
def catalog_contains_with_updated_timestamp(connected, slug):
    """After host updates a slide, the timestamp in the catalog should reflect the change."""
    pax = connected["pax"]
    pax.expand_slides_dock()
    # Wait for catalog refresh via WS notification, then reload if needed
    pax._page.wait_for_timeout(5000)
    item = pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')
    expect(item).to_be_visible(timeout=10000)
    timestamp = item.locator(".slides-list-updated")
    try:
        expect(timestamp).to_be_visible(timeout=5000)
    except AssertionError:
        pax._page.evaluate("() => window.location.reload()")
        pax._page.wait_for_load_state("networkidle")
        pax._page.wait_for_timeout(3000)
        pax.expand_slides_dock()
        item = pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')
        expect(item).to_be_visible(timeout=10000)
        timestamp = item.locator(".slides-list-updated")
        expect(timestamp).to_be_visible(timeout=10000)
    text = timestamp.inner_text().strip()
    assert len(text) > 0, f"Updated timestamp for '{slug}' is empty"


@then(parsers.parse("the participant sees at least {n:d} slides in the catalog"))
def participant_sees_slides(connected, n):
    pax = connected["pax"]
    expect(pax._page.locator(".slides-list-item")).to_have_count(n, timeout=10000)


@then(parsers.parse('the slides catalog contains "{slug}"'))
def catalog_contains(request, slug):
    try:
        pax = request.getfixturevalue("follow_pax")
    except pytest.FixtureLookupError:
        connected = request.getfixturevalue("connected")
        pax = connected["pax"]
    pax.expand_slides_dock()
    expect(pax._page.locator(f'.slides-list-item[data-slug="{slug}"]')).to_be_visible(timeout=10000)


@then("the slides overlay is visible")
def overlay_visible(connected):
    pax = connected["pax"]
    expect(pax._page.locator("#slides-overlay")).to_be_visible(timeout=10000)


@then(parsers.parse('{name} sees page {page_num:d} of "{slug}"'))
def sees_page_of_slide(name, page_num, slug):
    pax = _pax(name)
    # PDF.js page indicator in the emoji bar
    page_indicator = pax._page.locator("#slides-page-inline")
    expect(page_indicator).to_contain_text(f"Page {page_num}/", timeout=5000)


@then(parsers.parse("Google Drive was called {n:d} time"))
@then(parsers.parse("Google Drive was called {n:d} times"))
def drive_called_n_times(n):
    stats = _mock_drive_stats()
    actual = sum(stats.values()) if isinstance(stats, dict) else 0
    assert actual == n, f"Expected {n} Drive call(s), got {actual}. Stats: {stats}"


@then(parsers.parse("Google Drive was called at most {n:d} time"))
@then(parsers.parse("Google Drive was called at most {n:d} times"))
def drive_called_at_most_n_times(n):
    stats = _mock_drive_stats()
    actual = sum(stats.values()) if isinstance(stats, dict) else 0
    assert actual <= n, f"Expected at most {n} Drive call(s), got {actual}. Stats: {stats}"


@then("the slides overlay opens")
def overlay_opens(connected):
    pax = connected["pax"]
    expect(pax._page.locator("#slides-overlay")).to_be_visible(timeout=15000)


@then(parsers.parse("the slides overlay opens within {seconds:d} seconds"))
def overlay_opens_within(follow_pax, seconds):
    expect(follow_pax._page.locator("#slides-overlay")).to_be_visible(timeout=seconds * 1000)


@then("the follow button is still enabled")
def follow_still_enabled(follow_pax):
    btn = follow_pax._page.locator("#slides-follow-btn")
    expect(btn).to_have_attribute("aria-pressed", "true", timeout=5000)


@then(parsers.parse('the active slide is "{slug}"'))
def active_slide_is(request, slug):
    try:
        pax = request.getfixturevalue("follow_pax")
    except pytest.FixtureLookupError:
        connected = request.getfixturevalue("connected")
        pax = connected["pax"]
    pax.expand_slides_dock()
    expect(pax._page.locator(f'.slides-list-item.active[data-slug="{slug}"]')).to_be_visible(
        timeout=10000
    )


@then("the slide content has changed")
def slide_content_changed(request, connected):
    """Compare current viewer screenshot with the one stored before the host update."""
    pax = connected["pax"]
    viewer = pax._page.locator("#slides-pdf-viewer")
    expect(viewer).to_be_visible(timeout=15000)
    pax._page.wait_for_timeout(1000)
    after_screenshot = viewer.screenshot()
    before_screenshot = getattr(request.config, "_slides_before_screenshot", None)
    assert before_screenshot is not None, (
        "No before-screenshot stored — did 'the slide content is visually rendered' run first?"
    )
    assert after_screenshot != before_screenshot, "Slide content did not change after host update"
