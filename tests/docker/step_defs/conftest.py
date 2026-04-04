"""
Shared fixtures for pytest-bdd step definitions.

Provides session creation, browser launching, and page objects
reused across all feature scenarios.
"""

import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _api_call(method, path, data=None):
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _create_session(name="BDD Test") -> str:
    result = _api_call("POST", "/api/session/create", {"name": f"{name} {int(time.time())}", "type": "workshop"})
    return result["session_id"]


def _clear_qa(session_id: str) -> None:
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/qa/clear",
        method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
        data=b""
    )
    urllib.request.urlopen(req, timeout=5)


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


from pytest_bdd import given, when


@pytest.fixture
def session_id():
    """Create a fresh session for each scenario."""
    return _create_session()


# ── Shared Given steps ─────────────────────────────────────────────────────

@given("a fresh session", target_fixture="session_id")
def fresh_session(session_id):
    """session_id fixture from conftest provides a fresh session."""
    return session_id


@given("a host and participant are connected", target_fixture="connected")
def host_and_participant_connected(host_page, pax_page):
    """host_page and pax_page fixtures handle connection."""
    return {"host": host_page, "pax": pax_page}


@given("a host and 3 participants are connected", target_fixture="connected_multi")
def host_and_3_participants(host_page, pax_pages):
    return {"host": host_page, "pax_list": pax_pages}


@given("the host opens the Q&A tab")
def host_opens_qa(request):
    for name in ("connected", "connected_multi"):
        try:
            ctx = request.getfixturevalue(name)
            ctx["host"].open_qa_tab()
            return
        except pytest.FixtureLookupError:
            continue
    raise RuntimeError("No connected context fixture found")


@pytest.fixture
def pw():
    """Provide a Playwright instance for the scenario."""
    with sync_playwright() as p:
        yield p


@pytest.fixture
def browser(pw):
    """Launch a headless Chromium browser."""
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def host_page(browser, session_id):
    """Open host panel and return HostPage object."""
    ctx = browser.new_context(
        http_credentials={"username": HOST_USER, "password": HOST_PASS}
    )
    page = ctx.new_page()
    page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(page.locator("#tab-poll")).to_be_visible(timeout=10000)
    return HostPage(page)


@pytest.fixture
def pax_page(browser, session_id):
    """Open participant page and return ParticipantPage object (joined as 'Alice')."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join("Alice")
    return pax


@pytest.fixture
def pax_pages(browser, session_id):
    """Open 3 participant pages, joined as P1, P2, P3. Returns list of ParticipantPage."""
    participants = []
    for name in ["P1", "P2", "P3"]:
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        pax.join(name)
        participants.append(pax)
    return participants


@pytest.fixture
def late_pax(browser, session_id):
    """Factory fixture: call it to create a new participant that joins late."""
    def _make(name="LateJoiner"):
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        pax.join(name)
        return pax
    return _make
