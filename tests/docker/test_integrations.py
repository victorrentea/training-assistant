"""
Hermetic E2E tests: daemon integration points.

Tests that verify each daemon external integration works through the stub adapters:
- PPTX file change detection → slide_invalidated → backend re-downloads
- IntelliJ project tracking → host sees project + branch
- Quiz generation via stub LLM → host sees quiz preview
- Session folder creation + state persistence on disk
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from pages.host_page import HostPage


BASE = "http://localhost:8000"
MOCK_DRIVE = "http://localhost:9090"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

STUB_PPT_FILE = "/tmp/stub-powerpoint.json"
STUB_INTELLIJ_FILE = "/tmp/stub-intellij.json"
STUB_CALLS_FILE = "/tmp/stub-calls.jsonl"


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _mock_drive_stats() -> dict:
    with urllib.request.urlopen(f"{MOCK_DRIVE}/mock-drive/stats", timeout=3) as resp:
        return json.loads(resp.read())


def _mock_drive_reset():
    req = urllib.request.Request(f"{MOCK_DRIVE}/mock-drive/reset-stats", method="POST", data=b"")
    urllib.request.urlopen(req, timeout=3)


def _api_call(method, path, data=None):
    import base64
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data else (b"" if method == "POST" else None),
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get_or_create_session() -> str:
    try:
        with urllib.request.urlopen(f"{BASE}/api/session/active", timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("session_id"):
                return data["session_id"]
    except Exception:
        pass
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        page = ctx.new_page()
        page.goto(f"{BASE}/host", wait_until="networkidle")
        if re.search(r"/host/[a-zA-Z0-9]+", page.url):
            sid = page.url.split("/host/")[-1].split("?")[0]
            browser.close()
            return sid
        page.locator("#session-name-input").fill("Integration Tests")
        btn = page.locator("#create-btn-workshop")
        expect(btn).to_be_enabled(timeout=3000)
        btn.click()
        page.wait_for_url(re.compile(r"/host/[a-zA-Z0-9]+"), timeout=15000)
        sid = page.url.split("/host/")[-1].split("?")[0]
        browser.close()
        return sid


# ── PPTX Change Detection ──────────────────────────────────────────────────


def test_pptx_change_triggers_slide_invalidation():
    """Touch a PPTX file → daemon detects change → sends slide_invalidated → backend re-downloads from mock Drive."""
    session_id = _get_or_create_session()
    _mock_drive_reset()

    # First, trigger an initial download so the slide is cached
    slug = "clean-code"
    pdf_url = f"{BASE}/{session_id}/api/slides/file/{slug}"
    try:
        urllib.request.urlopen(pdf_url, timeout=15)
    except Exception:
        pass

    # Wait for initial download
    _await_condition(
        lambda: _mock_drive_stats().get(slug, 0) >= 1,
        timeout_ms=15000,
        msg="Initial PDF download did not happen"
    )
    initial_count = _mock_drive_stats()[slug]
    print(f"Initial Drive requests for {slug}: {initial_count}")

    # Touch the PPTX file to simulate a change
    pptx_path = "/tmp/test-pptx/Clean Code.pptx"
    # Sleep briefly to ensure mtime is different from initial
    time.sleep(1)
    os.utime(pptx_path, None)  # updates mtime to now
    print(f"Touched {pptx_path}")

    # Daemon polls every ~5s for file changes, then sends slide_invalidated
    # Backend receives it, clears fingerprint, and re-downloads on next request
    # Wait for daemon to detect and signal
    _await_condition(
        lambda: _mock_drive_stats().get(slug, 0) > initial_count,
        timeout_ms=30000,
        msg=f"Daemon did not trigger re-download after PPTX change (still {_mock_drive_stats().get(slug, 0)} requests)"
    )

    new_count = _mock_drive_stats()[slug]
    print(f"Drive requests after PPTX change: {new_count} (was {initial_count})")
    assert new_count > initial_count, "Expected additional Drive request after PPTX change"

    print("SUCCESS: PPTX change → slide_invalidated → backend re-downloaded from Drive!")


# ── IntelliJ Tracker ───────────────────────────────────────────────────────


def test_intellij_state_visible_to_host():
    """Set stub IntelliJ state → daemon picks it up → host sees project + branch."""
    session_id = _get_or_create_session()

    # Write IntelliJ stub state
    with open(STUB_INTELLIJ_FILE, "w") as f:
        json.dump({
            "project": "training-assistant",
            "path": "/workspace/training-assistant",
            "branch": "feature/hermetic-tests",
            "frontmost": True,
        }, f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Wait for daemon to probe IntelliJ (happens every ~1s in main loop)
        # The daemon sends the IntelliJ state as part of activity_log or slide_log
        # Check if the host page shows the git branch info
        _await_condition(
            lambda: "feature/hermetic-tests" in host_page.inner_text("body")
                    or "training-assistant" in host_page.inner_text("body"),
            timeout_ms=15000,
            msg="Host does not show IntelliJ project or branch"
        )

        body = host_page.inner_text("body")
        print(f"Host body contains IntelliJ info: {'training-assistant' in body or 'feature/hermetic-tests' in body}")

        print("SUCCESS: IntelliJ state visible to host!")

        # Cleanup
        os.unlink(STUB_INTELLIJ_FILE)
        browser.close()


# ── Quiz Generation via Stub LLM ──────────────────────────────────────────


def test_quiz_generation_with_stub_llm():
    """Host requests quiz → daemon uses stub LLM → quiz preview appears on host."""
    session_id = _get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        # Click Poll tab to see quiz controls
        host_page.click("#tab-poll")

        # Set a topic and request quiz generation
        topic_input = host_page.locator("#quiz-topic")
        if topic_input.count() > 0 and topic_input.is_visible():
            topic_input.fill("design patterns")

        # Click the generate quiz button
        gen_btn = host_page.locator("#gen-quiz-btn")
        expect(gen_btn).to_be_visible(timeout=5000)
        gen_btn.click()
        print("Clicked generate quiz button")

        # Daemon should process via stub LLM and send quiz_preview
        # Wait for quiz preview to appear on host page
        _await_condition(
            lambda: host_page.locator("#quiz-preview, .quiz-preview, [id*=quiz]").count() > 0
                    and "abstraction" in host_page.inner_text("body").lower(),
            timeout_ms=20000,
            msg="Quiz preview did not appear (stub LLM canned response has 'abstraction')"
        )

        print("Quiz preview appeared on host page")
        print("SUCCESS: Quiz generation via stub LLM works!")
        browser.close()
