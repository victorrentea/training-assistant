"""
Hermetic E2E test: Extract sequence diagram from OTel traces.

Tagged @pytest.mark.nightly — runs in nightly CI only.
"""
import os
import sys
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


@pytest.mark.nightly
def test_poll_sequence_diagram_extraction():
    """Exercise poll flow, extract sequence diagram from traces."""
    # Clear traces
    Path(TRACES_FILE).write_text("")

    session_id = fresh_session("SeqPoll")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        # Participant
        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Alice")

        # Exercise poll flow
        host.create_poll("What is 1+1?", ["1", "2", "3"])
        expect(pax._page.locator("#content h2")).to_have_text("What is 1+1?", timeout=5000)

        pax.vote_for("2")

        host.close_poll()
        expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)

        host.reveal_correct(["B"])
        pax._page.wait_for_timeout(1000)

        browser.close()

    # Wait a moment for spans to flush
    import time
    time.sleep(2)

    # Generate PlantUML from traces
    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/generated/03-poll-and-quiz.puml"
    generate_puml(TRACES_FILE, family="", output=output_path)  # no family filter — capture all spans

    # Debug: show raw traces
    traces_content = Path(TRACES_FILE).read_text()
    trace_lines = [line for line in traces_content.strip().split("\n") if line.strip()]
    print(f"=== Raw traces: {len(trace_lines)} spans ===")
    import json as _json
    services = set()
    for line in trace_lines:
        span = _json.loads(line)
        svc = span.get("resource", {}).get("service.name", "?")
        services.add(svc)
    print(f"  Services: {sorted(services)}")
    for line in trace_lines[:30]:
        span = _json.loads(line)
        svc = span.get("resource", {}).get("service.name", "?")
        print(f"  [{svc}] {span.get('name', '?')} parent={span.get('parent_id', '')[:8]}")

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    # Basic structural checks
    assert "@startuml" in generated
    assert len(trace_lines) > 0, "No spans collected — FileSpanExporter not active?"
    assert "->" in generated, f"No arrows in diagram. {len(trace_lines)} spans but no cross-service edges."

    print("SUCCESS: Sequence diagram extracted from traces")


def _generate_and_print(output_path):
    """Helper: generate PlantUML from traces file and print debug info."""
    import time

    time.sleep(2)  # wait for spans to flush

    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    generate_puml(TRACES_FILE, family="", output=output_path)

    traces_content = Path(TRACES_FILE).read_text()
    trace_lines = [line for line in traces_content.strip().split("\n") if line.strip()]
    print(f"=== Raw traces: {len(trace_lines)} spans ===")

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    assert "@startuml" in generated
    assert len(trace_lines) > 0, "No spans collected"
    assert "->" in generated, f"No arrows in diagram. {len(trace_lines)} spans but no cross-service edges."
    return generated


@pytest.mark.nightly
def test_qa_sequence_diagram_extraction():
    """Exercise Q&A flow, extract sequence diagram from traces."""
    Path(TRACES_FILE).write_text("")

    session_id = fresh_session("SeqQA")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        # Participant 1
        pax1_ctx = browser.new_context()
        pax1_raw = pax1_ctx.new_page()
        pax1_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_raw)
        pax1.join("Alice")

        # Participant 2
        pax2_ctx = browser.new_context()
        pax2_raw = pax2_ctx.new_page()
        pax2_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_raw)
        pax2.join("Bob")

        # Host opens Q&A (use evaluate to ensure switchTab runs)
        host_raw.evaluate("async () => { await switchTab('qa'); }")
        host_raw.wait_for_timeout(1000)

        # Alice submits a question
        pax1.submit_question("What is dependency injection?")
        pax1_raw.wait_for_timeout(500)

        # Bob upvotes Alice's question
        questions = pax2.get_qa_questions()
        if questions:
            pax2.upvote_question(questions[0]["id"])
            pax2_raw.wait_for_timeout(500)

        # Host marks question as answered
        host_questions = host.get_qa_questions()
        if host_questions:
            host.toggle_answered(host_questions[0]["id"])
            host_raw.wait_for_timeout(500)

        browser.close()

    output_path = "/app/docs/sequences/generated/04-qa-and-wordcloud.puml"
    _generate_and_print(output_path)
    print("SUCCESS: QA sequence diagram extracted from traces")


class _TracePhaseTracker:
    """Captures trace IDs from browser requests and maps them to BDD phases.

    Usage:
        tracker = _TracePhaseTracker()
        tracker.attach(page)       # start listening to requests
        tracker.phase = "given"    # set current phase
        # ... do actions ...
        tracker.phase = "when"     # switch phase
        # ... do actions ...
        trace_phases = tracker.trace_phases  # {trace_id: phase}
    """

    def __init__(self):
        self.phase = "given"
        self.trace_phases: dict[str, str] = {}

    def attach(self, page):
        page.on("request", self._on_request)

    def _on_request(self, request):
        tp = request.headers.get("traceparent", "")
        if tp:
            # traceparent format: 00-<trace_id>-<span_id>-<flags>
            parts = tp.split("-")
            if len(parts) >= 2:
                trace_id = parts[1]
                # Only record the first phase for each trace (the initiator)
                if trace_id not in self.trace_phases:
                    self.trace_phases[trace_id] = self.phase


@pytest.mark.nightly
def test_slides_sequence_diagram_extraction():
    """Exercise slides open flow, extract sequence diagram with BDD phase coloring."""
    Path(TRACES_FILE).write_text("")

    session_id = fresh_session("SeqSlides")
    tracker = _TracePhaseTracker()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── GIVEN: host connected, participant joined ──
        tracker.phase = "given"

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        tracker.attach(host_raw)
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)

        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        tracker.attach(pax_raw)
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Alice")

        # ── WHEN: participant opens a slide ──
        tracker.phase = "when"

        pax.expand_slides_dock()
        pax_raw.locator('.slides-list-item[data-slug="clean-code"] .slides-list-open').click()
        pax_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        pax_raw.wait_for_timeout(1000)

        browser.close()

    # Wait for spans to flush
    import time
    time.sleep(2)

    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/generated/06-slides.puml"
    print(f"[trace-phases] Captured {len(tracker.trace_phases)} trace IDs across phases")
    for tid, phase in sorted(tracker.trace_phases.items(), key=lambda x: x[1]):
        print(f"  {phase}: {tid[:16]}...")

    generate_puml(TRACES_FILE, family="", output=output_path,
                  trace_phases=tracker.trace_phases)

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    assert "@startuml" in generated
    assert "->" in generated
    # Verify some arrows are gray (given phase) and some are default (when phase)
    has_gray = "[#gray]" in generated
    has_default = any(
        '"->' in line and "[#gray]" not in line
        for line in generated.split("\n")
        if '"->' in line
    )
    print(f"Has gray arrows: {has_gray}, Has default arrows: {has_default}")
    assert has_gray, "Expected some gray (given-phase) arrows in the diagram"
    assert has_default, "Expected some default (when-phase) arrows in the diagram"

    print("SUCCESS: Slides sequence diagram with BDD phase coloring")
