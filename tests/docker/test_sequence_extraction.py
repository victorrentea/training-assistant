"""
Hermetic E2E test: Extract sequence diagram from OTel traces.

Tagged @pytest.mark.nightly — runs in nightly CI only.
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

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
TRACES_FILE = os.environ.get("OTEL_TRACES_FILE", "/tmp/traces.jsonl")


def _ns_now() -> int:
    return int(time.time() * 1_000_000_000)


def _auth_header() -> str:
    return base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _api(method, path, data=None, base_url=None):
    target = base_url or DAEMON_BASE
    body = json.dumps(data).encode() if data else (b"" if method in ("POST", "PUT") else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {_auth_header()}", "Content-Type": "application/json"},
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
        for name in self._pax_names:
            ctx = self._browser.new_context()
            self._contexts.append(ctx)
            page = ctx.new_page()
            page.goto(f"{BASE}/{self.session_id}", wait_until="networkidle")
            pax = ParticipantPage(page)
            pax.join(name)
            self._participants[name] = pax
        return self

    def __exit__(self, *_):
        for ctx in self._contexts:
            ctx.close()

    def participant(self, name: str = "Alice") -> ParticipantPage:
        return self._participants[name]

    def when(self):
        """Mark the Given→When boundary."""
        self._when_ns = _ns_now()

    @property
    def result(self) -> dict:
        return {"name": self._name, "when_start_ns": self._when_ns, "end_ns": _ns_now()}


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
        expect(pax._page.locator("#content h2")).to_have_text("What is 1+1?", timeout=5000)
        pax.vote_for("2")
        host.close_poll()
        expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)
        host.reveal_correct(["B"])
        pax._page.wait_for_timeout(1000)

        browser.close()

    time.sleep(2)
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/03-poll-and-quiz.puml"
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

        pax1.submit_question("What is dependency injection?")
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

    output_path = "/app/docs/sequences/extracted/04-qa-and-wordcloud.puml"
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Scenario 1: Participant opens a slide
        with ScenarioRunner(browser, "Participant opens a slide") as sc:
            alice = sc.participant()
            sc.when()
            alice.open_slide("clean-code")
        scenarios.append(sc.result)

        # Scenario 2: Two participants open the same (cached) slide
        with ScenarioRunner(browser, "Second participant gets cached slide",
                            participants=["Alice", "Bob"]) as sc:
            sc.when()
            sc.participant("Alice").open_slide("design-patterns")
            sc.participant("Bob").open_slide("design-patterns")
        scenarios.append(sc.result)

        # Scenario 3: Navigate between slides
        with ScenarioRunner(browser, "Navigate to page and resume") as sc:
            alice = sc.participant()
            sc.when()
            alice.open_slide("clean-code")
            alice.navigate_to_page(3)
            alice.open_slide("design-patterns")
        scenarios.append(sc.result)

        # Scenario 4: Host updates a slide (invalidation → re-download)
        with ScenarioRunner(browser, "Host updates a slide") as sc:
            sc.participant().open_slide("architecture")  # cache it (Given)
            sc.when()
            _, body = _api("GET", f"/{sc.session_id}/api/slides")
            slides = json.loads(body).get("slides", [])
            drive_url = next((s["drive_export_url"] for s in slides
                              if s.get("slug") == "architecture"), "")
            _api("POST", f"/api/{sc.session_id}/api/slides/invalidate/architecture",
                 data={"drive_export_url": drive_url}, base_url=BASE)
            sc.participant()._page.wait_for_timeout(3000)
        scenarios.append(sc.result)

        browser.close()

    time.sleep(2)
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/06-slides.puml"
    generate_puml(TRACES_FILE, family="", output=output_path, scenarios=scenarios,
                  title="Feature: Slides Catalog, Viewing, and Follow Mode")

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    assert "@startuml" in generated and "->" in generated
    assert "== Participant opens a slide ==" in generated
    assert "== Host updates a slide ==" in generated
    assert "group init" in generated
    print("SUCCESS: Slides sequence diagram with 4 scenarios")
