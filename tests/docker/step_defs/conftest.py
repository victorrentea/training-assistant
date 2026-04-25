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
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, "/tests")
from session_utils import fresh_session  # noqa: E402, I001

TRACES_FILE = os.environ.get("OTEL_TRACES_FILE", "/tmp/traces.jsonl")
SEQ_OUTPUT_DIR = "/app/docs/sequences/extracted"


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _api_call(method, path, data=None, base=None):
    """Make API call. Defaults to DAEMON_BASE for host endpoints."""
    target = base or DAEMON_BASE
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _clear_qa(session_id: str) -> None:
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/qa/clear",
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


from pytest_bdd import given, parsers  # noqa: E402, I001


def pytest_configure(config):
    """Register custom markers used by the BDD harness.

    The hermetic Docker image doesn't ship with pyproject.toml, so the
    marker registrations from there don't apply inside the container.
    Register them locally to silence PytestUnknownMarkWarning.
    """
    config.addinivalue_line(
        "markers", "nightly: slow tests run once per day in nightly CI",
    )
    config.addinivalue_line(
        "markers",
        "seq: scenarios exercised to produce a sequence-diagram PUML — also implies nightly",
    )


def pytest_bdd_apply_tag(tag, function):
    """Map BDD feature file tags to pytest marks.

    `@seq` implies `@nightly` because sequence-diagram scenarios spin up
    real browsers and traces — too slow for every-push CI.
    """
    if tag == "nightly":
        function.pytestmark = getattr(function, "pytestmark", []) + [pytest.mark.nightly]
        return True
    if tag == "seq":
        function.pytestmark = getattr(function, "pytestmark", []) + [
            pytest.mark.seq, pytest.mark.nightly,
        ]
        return True
    return None


# ── Sequence-diagram extraction harness ──────────────────────────────────
#
# When a scenario carries the `@seq` tag, the hooks below capture per-scenario
# timing (start/when-boundary/end) and OTel-friendly bdd.phase attributes on
# spans. After the test session finishes, scenarios are grouped by feature
# file and one `<feature>-sequence.puml` is emitted per group via
# `scripts.traces_to_puml.generate_puml`. SVGs are auto-rendered.

_seq_collector: dict = {
    "scenarios": [],          # list[dict]: one per @seq scenario
    "uuid_to_name": {},       # session-wide UUID → participant name
    "current": None,          # in-flight scenario timing dict
    "traces_cleared": False,
}


def _scenario_has_seq_tag(scenario) -> bool:
    return any(t == "seq" for t in (scenario.tags or set()))


def _capture_participant_uuids() -> None:
    """Read participant UUIDs from page localStorage into the session map.

    Step-def modules register live ParticipantPage objects in module-level
    `_participants` dicts. We harvest UUID→name mappings while the pages
    are still alive (i.e. during after-scenario, before browser teardown).
    """
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.endswith(".test_slides") and mod_name != "test_slides":
            continue
        pax_dict = getattr(mod, "_participants", None)
        if not isinstance(pax_dict, dict):
            continue
        for name, pax in pax_dict.items():
            try:
                uid = pax._page.evaluate(
                    "() => localStorage.getItem('workshop_participant_uuid')"
                )
                if uid:
                    _seq_collector["uuid_to_name"][uid] = name
            except Exception:
                pass


@pytest.hookimpl
def pytest_bdd_before_scenario(request, feature, scenario):
    if not _scenario_has_seq_tag(scenario):
        return
    if not _seq_collector["traces_cleared"]:
        Path(TRACES_FILE).write_text("")
        _seq_collector["traces_cleared"] = True
    _seq_collector["current"] = {
        "name": scenario.name,
        "feature_filename": Path(feature.filename).stem,
        "feature_title": feature.name,
        "start_ns": time.time_ns(),
        "when_start_ns": 0,
        "end_ns": 0,
    }


@pytest.hookimpl
def pytest_bdd_before_step(request, feature, scenario, step, step_func):
    """Tag spans with bdd.phase + capture Given→When boundary for @seq scenarios."""
    keyword = step.keyword.lower().strip()
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("bdd.phase", keyword)
    except ImportError:
        pass

    cur = _seq_collector["current"]
    if cur and cur["when_start_ns"] == 0 and keyword == "when":
        cur["when_start_ns"] = time.time_ns()


@pytest.hookimpl
def pytest_bdd_after_scenario(request, feature, scenario):
    cur = _seq_collector["current"]
    if not cur:
        return
    cur["end_ns"] = time.time_ns()
    _capture_participant_uuids()
    _seq_collector["scenarios"].append(cur)
    _seq_collector["current"] = None


def pytest_sessionfinish(session, exitstatus):
    if not _seq_collector["scenarios"]:
        return
    # Let any in-flight spans flush to the JSONL exporter.
    time.sleep(2)

    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    by_feature: dict[str, list[dict]] = {}
    feature_titles: dict[str, str] = {}
    for sc in _seq_collector["scenarios"]:
        feat = sc["feature_filename"]
        by_feature.setdefault(feat, []).append({
            "name": sc["name"],
            "start_ns": sc["start_ns"],
            "when_start_ns": sc["when_start_ns"] or sc["start_ns"],
            "end_ns": sc["end_ns"],
        })
        feature_titles[feat] = sc["feature_title"]

    Path(SEQ_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    for feat, scenarios in by_feature.items():
        output = f"{SEQ_OUTPUT_DIR}/{feat}-sequence.puml"
        generate_puml(
            TRACES_FILE,
            family="",
            output=output,
            scenarios=scenarios,
            title=f"Feature: {feature_titles[feat]}",
            participant_names=_seq_collector["uuid_to_name"],
        )
        print(f"[seq] generated {output} ({len(scenarios)} scenarios)")


@pytest.fixture
def session_id():
    """Create a fresh session for each scenario."""
    return fresh_session("BDD Test")


# ── Shared Given steps ─────────────────────────────────────────────────────

@given("a fresh session", target_fixture="session_id")
def given_fresh_session(session_id):
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


@given("the host has opened the Q&A tab", target_fixture="host_with_qa")
def host_has_opened_qa_tab(browser, session_id):
    """Open host panel and switch to Q&A tab BEFORE any participant joins.
    Returns a HostPage object. The Q&A activity is now set on the daemon,
    so participants who join next will see QA on their initial state fetch."""
    ctx = browser.new_context(
        http_credentials={"username": HOST_USER, "password": HOST_PASS}
    )
    page = ctx.new_page()
    page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(page.locator("#tab-poll")).to_be_visible(timeout=10000)
    host = HostPage(page)
    host.open_qa_tab()
    return host


@given(parsers.parse('a participant joins as "{name}"'), target_fixture="connected")
def participant_joins_as(host_with_qa, browser, session_id, name):
    """Join a participant AFTER host has opened Q&A tab."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(page)
    pax.join(name)
    return {"host": host_with_qa, "pax": pax}


@given("3 participants have joined", target_fixture="connected_multi")
def three_participants_joined(host_with_qa, browser, session_id):
    """Join 3 participants AFTER host has opened Q&A tab."""
    participants = []
    for name in ["P1", "P2", "P3"]:
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        pax.join(name)
        participants.append(pax)
    return {"host": host_with_qa, "pax_list": participants}


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
