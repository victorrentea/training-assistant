"""
Hermetic E2E test: Extract sequence diagram from OTel traces.

Tagged @pytest.mark.nightly — runs in nightly CI only.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
TRACES_FILE = os.environ.get("OTEL_TRACES_FILE", "/tmp/traces.jsonl")


def _ns_now() -> int:
    return int(time.time() * 1_000_000_000)


def _auth_header() -> str:
    return base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


_FEATURE_SCENARIO_RE = re.compile(r"^\s*Scenario:\s*(.+?)\s*$")


def feature_scenario(feature_path: str, keyword: str) -> str:
    """Return the scenario name from feature_path that contains keyword.

    Lets the diagram-section labels in the generated PUML stay in sync with
    the canonical Gherkin "Scenario:" lines in the .feature files instead
    of being hardcoded twice. Match is case-insensitive and uses a unique
    substring so renames in the feature file surface as a clear failure.
    """
    text = Path(feature_path).read_text(encoding="utf-8")
    matches = []
    for line in text.splitlines():
        m = _FEATURE_SCENARIO_RE.match(line)
        if m and keyword.lower() in m.group(1).lower():
            matches.append(m.group(1))
    if not matches:
        raise ValueError(
            f"No scenario containing {keyword!r} in {feature_path}")
    if len(matches) > 1:
        raise ValueError(
            f"Keyword {keyword!r} matches multiple scenarios in {feature_path}: {matches}")
    return matches[0]


def _api(method, path, data=None, base_url=None, actor=None):
    target = base_url or DAEMON_BASE
    body = json.dumps(data).encode() if data else (b"" if method in ("POST", "PUT") else None)
    headers = {"Authorization": f"Basic {_auth_header()}", "Content-Type": "application/json"}
    if actor:
        # Captured as the "actor" span attribute by FastAPI's request hook;
        # used by traces_to_puml.py to label the originating actor on
        # otherwise-rootless Railway requests (e.g. "FileSystem" for the
        # daemon's PPTX-watcher-driven invalidate flow).
        headers["X-Actor"] = actor
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers=headers,
        data=body,
    )
    if method in ("POST", "PUT") and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read()


# ── Reusable scenario runner ──────────────────────────────────────────


class ScenarioRunner:
    """Sets up host + participants, tracks Given/When phase boundary.

    Usage:
        with ScenarioRunner(browser, "Open a slide") as sc:
            alice = sc.participant()
            sc.when()
            alice.open_slide("clean-code")
        scenarios.append(sc.result)
    """

    def __init__(self, browser, name: str, participants: list[str] | None = None):
        self._browser = browser
        self._name = name
        self._pax_names = participants or ["Alice"]
        self._contexts: list = []
        self._participants: dict[str, ParticipantPage] = {}
        self.session_id = ""
        self.host_page = None
        self._when_ns = 0

    def __enter__(self):
        self._start_ns = _ns_now()
        self.session_id = fresh_session(f"Seq-{self._name[:20]}")
        # Host
        ctx = self._browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        self._contexts.append(ctx)
        self.host_page = ctx.new_page()
        self.host_page.goto(f"{DAEMON_BASE}/host/{self.session_id}", wait_until="networkidle")
        expect(self.host_page.locator("#tab-poll")).to_be_visible(timeout=10000)
        # Participants
        self._uuid_to_name: dict[str, str] = {}
        for name in self._pax_names:
            ctx = self._browser.new_context()
            self._contexts.append(ctx)
            page = ctx.new_page()
            # ?as=NAME makes the page register with the name in one shot,
            # so the diagram shows POST /register only (no follow-up
            # PUT /name). Diagrams stay focused on real workshop traffic
            # rather than the dev shorthand of "join then rename".
            from urllib.parse import quote
            page.goto(f"{BASE}/{self.session_id}?as={quote(name)}", wait_until="networkidle")
            pax = ParticipantPage(page)
            pax.join(name)
            self._participants[name] = pax
            # Capture UUID for trace→name resolution
            uid = page.evaluate("() => localStorage.getItem('workshop_participant_uuid')")
            if uid:
                self._uuid_to_name[uid] = name
        return self

    def __exit__(self, *_):
        for ctx in self._contexts:
            ctx.close()

    def participant(self, name: str = "Alice") -> ParticipantPage:
        return self._participants[name]

    def when(self):
        """Mark the Given→When boundary.

        Waits for setup-related traces (participant rename's
        participant_list_updated, the throttled active_participants_count_updated
        broadcast, any in-flight client polling, etc.) to drain so they end up
        inside the init group instead of bleeding into the When phase.
        """
        for page in [self.host_page] + [p._page for p in self._participants.values()]:
            if page is None:
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
        # The Railway active_participants_count_updated broadcast is throttled
        # at ~1s — wait past it so the broadcast lands in init, not in when.
        time.sleep(1.1)
        self._when_ns = _ns_now()

    @property
    def uuid_to_name(self) -> dict[str, str]:
        """UUID→name mapping for all participants in this scenario."""
        return dict(self._uuid_to_name)

    @property
    def result(self) -> dict:
        return {
            "name": self._name,
            "start_ns": self._start_ns,
            "when_start_ns": self._when_ns,
            "end_ns": _ns_now(),
        }


# ── Sequence extraction tests ──────────────────────────────────────────


@pytest.mark.nightly
def test_poll_sequence_diagram_extraction():
    """Exercise poll flow, extract sequence diagram from traces."""
    Path(TRACES_FILE).write_text("")
    session_id = fresh_session("SeqPoll")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Alice")

        host.create_poll("What is 1+1?", ["1", "2", "3"])
        pax._page.wait_for_timeout(500)  # Wait for poll to broadcast to participant
        # Vote via API (no poll UI in new participant page)
        pax._page.evaluate("""async () => {
            await fetch('/' + _sessionId + '/api/participant/poll/vote', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'x-participant-id': _myUUID},
                body: JSON.stringify({option_ids: ['B']})
            });
        }""")
        host.close_poll()
        host.reveal_correct(["B"])
        pax._page.wait_for_timeout(1000)

        browser.close()

    time.sleep(2)
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/03-poll-and-quiz-sequence.puml"
    generate_puml(TRACES_FILE, family="", output=output_path)
    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)
    assert "@startuml" in generated and "->" in generated
    print("SUCCESS: Poll sequence diagram extracted")


@pytest.mark.nightly
def test_qa_sequence_diagram_extraction():
    """Exercise Q&A flow, extract sequence diagram from traces."""
    Path(TRACES_FILE).write_text("")
    session_id = fresh_session("SeqQA")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        pax1_ctx = browser.new_context()
        pax1_raw = pax1_ctx.new_page()
        pax1_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_raw)
        pax1.join("Alice")

        pax2_ctx = browser.new_context()
        pax2_raw = pax2_ctx.new_page()
        pax2_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_raw)
        pax2.join("Bob")

        host_raw.evaluate("async () => { await switchTab('qa'); }")
        host_raw.wait_for_timeout(1000)

        # Submit question via API (no QA input in new participant page)
        pax1._page.evaluate("""async () => {
            await fetch('/' + _sessionId + '/api/participant/qa/submit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'x-participant-id': _myUUID},
                body: JSON.stringify({text: 'What is dependency injection?'})
            });
        }""")
        pax1_raw.wait_for_timeout(500)
        questions = pax2.get_qa_questions()
        if questions:
            pax2.upvote_question(questions[0]["id"])
            pax2_raw.wait_for_timeout(500)
        host_questions = host.get_qa_questions()
        if host_questions:
            host.toggle_answered(host_questions[0]["id"])
            host_raw.wait_for_timeout(500)

        browser.close()

    time.sleep(2)
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/04-qa-and-wordcloud-sequence.puml"
    generate_puml(TRACES_FILE, family="", output=output_path)
    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)
    assert "@startuml" in generated and "->" in generated
    print("SUCCESS: QA sequence diagram extracted")


@pytest.mark.nightly
def test_slides_sequence_diagram_extraction():
    """Exercise slides scenarios using ScenarioRunner, generate diagram with phase coloring."""
    Path(TRACES_FILE).write_text("")
    scenarios = []
    all_participant_names: dict[str, str] = {}  # UUID → name across all scenarios

    # Diagram section labels are pulled from the slides.feature file so the
    # extracted PUML stays in sync with the canonical Gherkin names. Each
    # keyword below must uniquely match exactly one scenario in the feature.
    feature_path = "/tests/features/slides.feature"
    name_opens_slide = feature_scenario(feature_path, "opens a slide and sees rendered")
    name_cached_slide = feature_scenario(feature_path, "Second participant gets cached")
    name_navigate_resume = feature_scenario(feature_path, "Navigating back to a slide")
    name_host_updates = feature_scenario(feature_path, "auto-refreshed when host updates")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Scenario 1: Participant opens a slide
        with ScenarioRunner(browser, name_opens_slide) as sc:
            alice = sc.participant()
            sc.when()
            alice.open_slide("clean-code")
        scenarios.append(sc.result)
        all_participant_names.update(sc.uuid_to_name)

        # Scenario 2: Two participants open the same (cached) slide
        with ScenarioRunner(browser, name_cached_slide,
                            participants=["Alice", "Bob"]) as sc:
            sc.when()
            sc.participant("Alice").open_slide("design-patterns")
            sc.participant("Bob").open_slide("design-patterns")
        scenarios.append(sc.result)
        all_participant_names.update(sc.uuid_to_name)

        # Scenario 3: Navigate between slides
        with ScenarioRunner(browser, name_navigate_resume) as sc:
            alice = sc.participant()
            sc.when()
            alice.open_slide("clean-code")
            alice.navigate_to_page(3)
            alice.open_slide("design-patterns")
        scenarios.append(sc.result)
        all_participant_names.update(sc.uuid_to_name)

        # Scenario 4: Host updates a slide (invalidation → re-download)
        # Per the Gherkin scenario, both "Alice opens slide" and "host updates"
        # are When steps — so when() comes BEFORE the open_slide call.
        with ScenarioRunner(browser, name_host_updates) as sc:
            sc.when()
            sc.participant().open_slide("architecture")
            # Hit the daemon's test endpoint (which mirrors the production
            # PPTX-watcher path) so the trace shows
            #   FileSystem -> Daemon -> Railway -> GDrive
            # rather than skipping the daemon hop.
            _api("POST", "/test/pptx-update-detected",
                 data={"slug": "architecture", "session_id": sc.session_id},
                 actor="FileSystem")
            sc.participant()._page.wait_for_timeout(3000)
        scenarios.append(sc.result)
        all_participant_names.update(sc.uuid_to_name)

        browser.close()

    print(f"[participant-names] {len(all_participant_names)} UUIDs mapped")
    time.sleep(2)
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/06-slides-sequence.puml"
    generate_puml(TRACES_FILE, family="", output=output_path, scenarios=scenarios,
                  title="Feature: Slides Catalog, Viewing, and Follow Mode",
                  participant_names=all_participant_names)

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    assert "@startuml" in generated and "->" in generated
    assert f"== {name_opens_slide} ==" in generated
    assert f"== {name_host_updates} ==" in generated
    assert "group #F5F5F5 init" in generated
    print("SUCCESS: Slides sequence diagram with 4 scenarios")
