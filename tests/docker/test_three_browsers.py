"""
Prove that 3 isolated browser contexts + FastAPI all work in one Docker container.

Each context gets its own localStorage, cookies, and session — no leakage.
"""

import subprocess
import time
import signal
import os

import pytest
from playwright.sync_api import sync_playwright


BASE = "http://localhost:8000"


@pytest.fixture(scope="session", autouse=True)
def fastapi_server():
    """Start uvicorn in the background, wait for it, tear down after tests."""
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "dummy_app:app", "--host", "0.0.0.0", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(BASE)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("FastAPI server did not start")

    yield proc

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


def test_three_contexts_are_isolated():
    """3 browser contexts each get independent localStorage."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context()
        pax1_ctx = browser.new_context()
        pax2_ctx = browser.new_context()

        host_page = host_ctx.new_page()
        pax1_page = pax1_ctx.new_page()
        pax2_page = pax2_ctx.new_page()

        # Each context sets a different name via localStorage
        host_page.goto(f"{BASE}/set-name/HostUser")
        pax1_page.goto(f"{BASE}/set-name/Participant1")
        pax2_page.goto(f"{BASE}/set-name/Participant2")

        # Now visit home — each should see THEIR name, not another's
        host_page.goto(BASE)
        pax1_page.goto(BASE)
        pax2_page.goto(BASE)

        assert host_page.inner_text("#name") == "HostUser"
        assert pax1_page.inner_text("#name") == "Participant1"
        assert pax2_page.inner_text("#name") == "Participant2"

        browser.close()


def test_cookies_are_isolated():
    """Cookies set in one context are invisible to others."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        ctx_a = browser.new_context()
        ctx_b = browser.new_context()

        page_a = ctx_a.new_page()
        page_b = ctx_b.new_page()

        # Set a cookie in context A
        page_a.goto(BASE)
        page_a.evaluate("document.cookie = 'session=abc123; path=/'")

        # Context B should not see it
        page_b.goto(BASE)
        cookie_b = page_b.evaluate("document.cookie")

        assert "abc123" not in cookie_b, "Cookie leaked between contexts!"

        browser.close()


def test_all_three_see_same_server_content():
    """All 3 contexts hit the same FastAPI and get the same base HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        pages = []
        for _ in range(3):
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(BASE)
            pages.append(page)

        for page in pages:
            assert page.inner_text("#greeting") == "Hello from FastAPI in Docker!"

        browser.close()
