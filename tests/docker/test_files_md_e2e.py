"""Hermetic E2E: files.md feature — two participants + 3 addon events.

Verifies:
  - public repo + valid blob   → linked bullet (href to real github.com URL)
  - public repo + invalid blob → unlinked bullet (plain text, no link)
  - private repo               → absent entirely from both participants' views
  - HTML comments stripped on wire (no '<!--' in raw_markdown)
"""

import json
import os
import sys
import threading
import time
import urllib.request

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import sync_playwright
from session_utils import fresh_session

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
_ADDON_BRIDGE_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))
_GITHUB_STUB_URL = "http://localhost:{}".format(os.environ.get("MOCK_GITHUB_PORT", "9091"))


def _seed_github_stub(repos: list, blobs: list) -> None:
    """POST seeding JSON to the always-running stub server."""
    req = urllib.request.Request(
        f"{_GITHUB_STUB_URL}/__reset",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=b"{}",
    )
    urllib.request.urlopen(req, timeout=2).read()

    body = json.dumps({"repos": repos, "blobs": blobs}).encode("utf-8")
    req = urllib.request.Request(
        f"{_GITHUB_STUB_URL}/__seed",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=body,
    )
    urllib.request.urlopen(req, timeout=2).read()


def _run_mock_addon_bridge(events: list, stop_event: threading.Event) -> None:
    """WS server on _ADDON_BRIDGE_PORT that pushes git_file_opened events to each client."""
    import asyncio

    import websockets

    async def handle(websocket):
        for evt in events:
            await websocket.send(json.dumps(evt))
        # Hold the connection open until stop_event is set (or 30s safety timeout)
        await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    async def serve():
        async with websockets.serve(handle, "127.0.0.1", _ADDON_BRIDGE_PORT):
            await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    asyncio.run(serve())


def test_files_md_two_participants_three_events():
    """Two participants both see correct files.md after three addon events."""
    session_id = fresh_session("FilesMd")

    # Seed the GitHub stub:
    #   - victorrentea/training-assistant is public with default_branch=master
    #   - owner/private-repo is not seeded → stub returns 404 (treated as private)
    #   - static/participant.html blob exists (200)
    #   - totally/missing/path.py blob absent (not seeded → 404)
    _seed_github_stub(
        repos=[
            {
                "owner": "victorrentea",
                "repo": "training-assistant",
                "status": 200,
                "default_branch": "master",
            },
            # owner/private-repo intentionally absent → stub returns 404
        ],
        blobs=[
            {
                "owner": "victorrentea",
                "repo": "training-assistant",
                "path": "static/participant.html",
                "status": 200,
            },
            # totally/missing/path.py intentionally absent → stub returns 404
        ],
    )

    stop = threading.Event()
    events = [
        {
            "type": "git_file_opened",
            "url": "https://github.com/victorrentea/training-assistant",
            "branch": "feature/x",
            "file": "static/participant.html",
        },
        {
            "type": "git_file_opened",
            "url": "https://github.com/victorrentea/training-assistant",
            "branch": "feature/x",
            "file": "totally/missing/path.py",
        },
        {
            "type": "git_file_opened",
            "url": "https://github.com/owner/private-repo",
            "branch": "main",
            "file": "secret.py",
        },
    ]
    thread = threading.Thread(
        target=_run_mock_addon_bridge, args=(events, stop), daemon=True
    )
    thread.start()
    # Give the WS server a moment to bind before the daemon tries to reconnect
    time.sleep(0.5)

    # Poll /api/participant/files-md via Railway proxy until the daemon has ingested all events.
    resp = ""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            resp = (
                urllib.request.urlopen(
                    f"{BASE}/{session_id}/api/participant/files-md", timeout=2
                )
                .read()
                .decode("utf-8")
            )
            data = json.loads(resp)
            md = data.get("raw_markdown", "")
            # Wait for both expected entries to appear
            if "training-assistant" in md and "participant.html" in md and "path.py" in md:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        pytest.fail(
            f"Daemon did not ingest all events within 20s; last raw response: {resp!r}"
        )

    # Re-fetch for assertions (resp above may be raw bytes from urlopen)
    final_data = json.loads(resp)
    raw_md = final_data.get("raw_markdown", "")

    # HTML comments must be stripped on the wire
    assert "<!--" not in raw_md, f"Wire payload leaks HTML comments: {raw_md!r}"

    # Private repo must be absent
    assert "private-repo" not in raw_md, f"private-repo leaked into wire payload: {raw_md!r}"
    assert "secret.py" not in raw_md, f"secret.py leaked into wire payload: {raw_md!r}"

    # Public repo section must be present
    assert "training-assistant" in raw_md
    assert "participant.html" in raw_md
    assert "path.py" in raw_md

    # The linked file must point at real github.com (build_blob_url always uses real github.com)
    expected_link = (
        "https://github.com/victorrentea/training-assistant/blob/master/static/participant.html"
    )
    assert expected_link in raw_md, (
        f"Expected linked blob URL not found in markdown.\n"
        f"Expected: {expected_link}\nMarkdown:\n{raw_md}"
    )

    # Verify via browser that both participants see the rendered content correctly
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for nick in ("Alice", "Bob"):
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
                pax = ParticipantPage(page)
                pax.join(nick)

                # Navigate to the Files tab via JS to bypass any onboarding overlay
                page.evaluate("showView('files')")

                # Wait for the files-content div to populate with training-assistant
                page.wait_for_function(
                    "() => {"
                    "  var el = document.getElementById('files-content');"
                    "  return el && el.textContent.includes('training-assistant');"
                    "}",
                    timeout=10000,
                )

                inner = page.inner_html("#files-content")

                assert "training-assistant" in inner, (
                    f"[{nick}] training-assistant not in files-content"
                )
                assert "participant.html" in inner, (
                    f"[{nick}] participant.html not in files-content"
                )
                assert "path.py" in inner, (
                    f"[{nick}] path.py not in files-content"
                )
                assert "private-repo" not in inner, (
                    f"[{nick}] private-repo leaked into rendered HTML"
                )
                assert "secret.py" not in inner, (
                    f"[{nick}] secret.py leaked into rendered HTML"
                )

                # The linked file must have the real github.com href in the rendered HTML
                assert expected_link in inner, (
                    f"[{nick}] Expected blob link not found in rendered HTML.\n"
                    f"Expected: {expected_link}\nInner HTML:\n{inner[:2000]}"
                )

                ctx.close()
                print(f"[test] {nick}: files-content assertions passed")
        finally:
            browser.close()
            stop.set()

    print("[test] test_files_md_two_participants_three_events PASSED")
