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

    output_path = "/app/docs/sequences/extracted/03-poll-and-quiz.puml"
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

    output_path = "/app/docs/sequences/extracted/04-qa-and-wordcloud.puml"
    _generate_and_print(output_path)
    print("SUCCESS: QA sequence diagram extracted from traces")


def _ns_now() -> int:
    """Current time in nanoseconds (matches OTel span start_time format)."""
    import time
    return int(time.time() * 1_000_000_000)


@pytest.mark.nightly
def test_slides_sequence_diagram_extraction():
    """Exercise multiple slides scenarios, generate diagram with phase coloring + separators."""
    Path(TRACES_FILE).write_text("")

    scenarios = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ═══════════════════════════════════════════════════════════
        # Scenario 1: Participant opens a slide
        # ════════════════════════════════════���══════════════════════
        session_id = fresh_session("SeqSlides1")

        # GIVEN: host connected, participant joined
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)

        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Alice")

        when_start1 = _ns_now()

        # WHEN: Alice opens a slide
        pax.expand_slides_dock()
        pax_raw.locator('.slides-list-item[data-slug="clean-code"] .slides-list-open').click()
        pax_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        pax_raw.wait_for_timeout(500)

        scenarios.append({
            "name": "Participant opens a slide",
            "when_start_ns": when_start1,
            "end_ns": _ns_now(),
        })
        host_ctx.close()
        pax_ctx.close()

        # ═══════════════════════════════════════════════════════════
        # Scenario 2: Second participant gets cached slide
        # ════���═════════════════════════════════════════════���════════
        session_id2 = fresh_session("SeqSlides2")

        # GIVEN
        host_ctx2 = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw2 = host_ctx2.new_page()
        host_raw2.goto(f"{DAEMON_BASE}/host/{session_id2}", wait_until="networkidle")
        expect(host_raw2.locator("#tab-poll")).to_be_visible(timeout=10000)

        alice_ctx = browser.new_context()
        alice_raw = alice_ctx.new_page()
        alice_raw.goto(f"{BASE}/{session_id2}", wait_until="networkidle")
        alice = ParticipantPage(alice_raw)
        alice.join("Alice")

        bob_ctx = browser.new_context()
        bob_raw = bob_ctx.new_page()
        bob_raw.goto(f"{BASE}/{session_id2}", wait_until="networkidle")
        bob = ParticipantPage(bob_raw)
        bob.join("Bob")

        when_start2 = _ns_now()

        # WHEN: Both open the same slide
        alice.expand_slides_dock()
        alice_raw.locator('.slides-list-item[data-slug="design-patterns"] .slides-list-open').click()
        alice_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        alice_raw.wait_for_timeout(500)

        bob.expand_slides_dock()
        bob_raw.locator('.slides-list-item[data-slug="design-patterns"] .slides-list-open').click()
        bob_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        bob_raw.wait_for_timeout(500)

        scenarios.append({
            "name": "Second participant gets cached slide",
            "when_start_ns": when_start2,
            "end_ns": _ns_now(),
        })
        host_ctx2.close()
        alice_ctx.close()
        bob_ctx.close()

        # ═══════════════════════════════════════════════════════════
        # Scenario 3: Navigate to page and resume
        # ═══════════════════════════════════════════════════════════
        session_id3 = fresh_session("SeqSlides3")

        host_ctx3 = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw3 = host_ctx3.new_page()
        host_raw3.goto(f"{DAEMON_BASE}/host/{session_id3}", wait_until="networkidle")
        expect(host_raw3.locator("#tab-poll")).to_be_visible(timeout=10000)

        pax3_ctx = browser.new_context()
        pax3_raw = pax3_ctx.new_page()
        pax3_raw.goto(f"{BASE}/{session_id3}", wait_until="networkidle")
        pax3 = ParticipantPage(pax3_raw)
        pax3.join("Alice")

        when_start3 = _ns_now()

        # WHEN: open slide, navigate to page 3, switch slide, come back
        pax3.expand_slides_dock()
        pax3_raw.locator('.slides-list-item[data-slug="clean-code"] .slides-list-open').click()
        pax3_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        pax3.navigate_to_page(3)
        pax3_raw.locator('.slides-list-item[data-slug="design-patterns"] .slides-list-open').click()
        pax3_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        pax3_raw.wait_for_timeout(500)

        scenarios.append({
            "name": "Navigate to page and resume",
            "when_start_ns": when_start3,
            "end_ns": _ns_now(),
        })
        host_ctx3.close()
        pax3_ctx.close()

        # ═══════════════════════════════════════════════════════════
        # Scenario 4: Host updates a slide (invalidation flow)
        # ═══════════════════════════════════════════════════════════
        session_id4 = fresh_session("SeqSlides4")

        host_ctx4 = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw4 = host_ctx4.new_page()
        host_raw4.goto(f"{DAEMON_BASE}/host/{session_id4}", wait_until="networkidle")
        expect(host_raw4.locator("#tab-poll")).to_be_visible(timeout=10000)

        pax4_ctx = browser.new_context()
        pax4_raw = pax4_ctx.new_page()
        pax4_raw.goto(f"{BASE}/{session_id4}", wait_until="networkidle")
        pax4 = ParticipantPage(pax4_raw)
        pax4.join("Alice")

        # Open slide first so it's cached
        pax4.expand_slides_dock()
        pax4_raw.locator('.slides-list-item[data-slug="architecture"] .slides-list-open').click()
        pax4_raw.wait_for_selector("#slides-pdf-viewer canvas", timeout=30000)
        pax4_raw.wait_for_timeout(500)

        when_start4 = _ns_now()

        # WHEN: host invalidates the slide (simulates updating the Google Drive file)
        import json as _json
        import urllib.request as _ur
        import base64 as _b64
        auth = _b64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        # Get drive_export_url from catalog
        req = _ur.Request(
            f"{DAEMON_BASE}/{session_id4}/api/slides",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        )
        with _ur.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        slides_list = data.get("slides", data) if isinstance(data, dict) else data
        drive_url = ""
        for s in slides_list:
            if s.get("slug") == "architecture":
                drive_url = s.get("drive_export_url", "")
                break
        # Invalidate
        inv_body = _json.dumps({"drive_export_url": drive_url}).encode()
        inv_req = _ur.Request(
            f"{BASE}/api/{session_id4}/api/slides/invalidate/architecture",
            method="POST",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            data=inv_body,
        )
        _ur.urlopen(inv_req, timeout=10)
        pax4_raw.wait_for_timeout(3000)  # wait for re-download + broadcast

        scenarios.append({
            "name": "Host updates a slide",
            "when_start_ns": when_start4,
            "end_ns": _ns_now(),
        })
        host_ctx4.close()
        pax4_ctx.close()

        browser.close()

    # Wait for spans to flush
    import time
    time.sleep(2)

    sys.path.insert(0, "/app")
    from scripts.traces_to_puml import generate_puml

    output_path = "/app/docs/sequences/extracted/06-slides.puml"
    generate_puml(TRACES_FILE, family="", output=output_path, scenarios=scenarios,
                  title="Feature: Slides Catalog, Viewing, and Follow Mode")

    generated = Path(output_path).read_text()
    print("=== Generated PlantUML ===")
    print(generated)

    assert "@startuml" in generated
    assert "->" in generated
    # Verify scenario separators
    assert "== Participant opens a slide ==" in generated
    assert "== Second participant gets cached slide ==" in generated
    assert "== Navigate to page and resume ==" in generated
    assert "== Host updates a slide ==" in generated
    # Verify init blocks
    assert "group init" in generated

    print("SUCCESS: Slides sequence diagram with 4 scenarios and phase coloring")
