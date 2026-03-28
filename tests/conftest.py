"""
Shared fixtures for e2e browser tests.

Spins up a real uvicorn server on a free port, provides browser/page
fixtures for host and participant roles, and cleanup fixtures for each
activity type.
"""

import os
import re
import subprocess
import sys
import time
import threading

# Ensure project root and tests dir are on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tests_dir = os.path.dirname(os.path.abspath(__file__))
for _p in (_project_root, _tests_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import requests
import pytest

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage

HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_server_port = {"port": None}  # set by server_url fixture, read by pax_url()


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    """
    Spin up uvicorn on port 0 (OS picks a free port atomically).
    Parse the actual bound port from uvicorn's stderr output.

    When --cov is active, the server runs under ``coverage run`` so that
    backend line coverage is collected and combined automatically.
    """
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_env = os.environ.copy()
    server_env["HOST_USERNAME"] = HOST_USER
    server_env["HOST_PASSWORD"] = HOST_PASS

    # Provide a test catalog with one unavailable slide (no PDF on disk)
    # so e2e tests can verify the unavailable-slide UI behaviour.
    catalog_path = tmp_path_factory.mktemp("catalog") / "test_catalog.json"
    catalog_path.write_text(json.dumps({
        "slides": [{"name": "E2E Unavailable Slide", "target_pdf": "e2e-unavailable-slide.pdf",
                    "slug": "e2e-unavailable-slide"}]
    }), encoding="utf-8")
    server_env["PPTX_CATALOG_FILE"] = str(catalog_path)

    # Detect whether pytest-cov is active
    use_coverage = os.environ.get("_E2E_COVERAGE") == "1"
    cov_data_file = None

    if use_coverage:
        cov_data_file = os.path.join(project_dir, ".coverage.server")
        cmd = [
            sys.executable, "-m", "coverage", "run",
            "--source=.,routers",
            f"--data-file={cov_data_file}",
            "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", "0",
        ]
    else:
        cmd = [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", "0",
        ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=project_dir,
        env=server_env,
    )

    port = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stderr.readline().decode("utf-8", errors="replace")
        m = re.search(r"127\.0\.0\.1:(\d+)", line)
        if m:
            port = int(m.group(1))
            break
        if proc.poll() is not None:
            raise RuntimeError("uvicorn exited unexpectedly during startup")
    else:
        proc.terminate()
        raise RuntimeError("uvicorn did not log a bound port within 15s")

    threading.Thread(target=proc.stderr.read, daemon=True).start()

    base_url = f"http://127.0.0.1:{port}"

    # Start a session so participant routes are accessible
    r = requests.post(
        f"{base_url}/api/session/start",
        auth=(HOST_USER, HOST_PASS),
        json={"name": "e2e-test"},
    )
    r.raise_for_status()

    _server_port["port"] = port

    yield base_url

    # Send SIGINT (KeyboardInterrupt) so coverage.py gets to flush data
    import signal
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(server_url, method, path, **kwargs):
    """Authenticated API call to a host-only endpoint."""
    return getattr(requests, method)(
        f"{server_url}{path}",
        auth=(HOST_USER, HOST_PASS),
        **kwargs,
    )


_cached_session_id = [None]  # list so it's mutable across module copies


def _get_session_id():
    """Fetch session ID from running server (cached after first call)."""
    if _cached_session_id[0]:
        return _cached_session_id[0]
    port = _server_port.get("port") if isinstance(_server_port, dict) else None
    if not port:
        # Fallback: try all module copies
        import sys
        for mod in sys.modules.values():
            sp = getattr(mod, "_server_port", None)
            if isinstance(sp, dict) and sp.get("port"):
                port = sp["port"]
                break
    assert port, "No server port — server_url fixture must run first"
    r = requests.get(
        f"http://127.0.0.1:{port}/api/session/snapshot",
        auth=(HOST_USER, HOST_PASS),
    )
    r.raise_for_status()
    sid = r.json().get("session_id")
    assert sid, "No session_id in snapshot"
    _cached_session_id[0] = sid
    return sid


@pytest.fixture(scope="session")
def session_id(server_url):
    """Return the active session ID (created by server_url fixture)."""
    return _get_session_id()


def pax_url(path="/"):
    """Return session-scoped participant URL path. Use in tests that create their own browser contexts.
    Example: page.goto(pax_url()) instead of page.goto("/")"""
    sid = _get_session_id()
    if path == "/":
        return f"/{sid}"
    return f"/{sid}{path}"


def host_browser_ctx(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(
        base_url=server_url,
        http_credentials={"username": HOST_USER, "password": HOST_PASS},
        viewport={"width": 1440, "height": 900},
    )
    return browser, ctx


def pax_browser_ctx(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(base_url=server_url)
    # Suppress the onboarding tour so it doesn't intercept test clicks
    ctx.add_init_script("localStorage.setItem('workshop_tour_shown', '1')")
    return browser, ctx


# ---------------------------------------------------------------------------
# Browser / page fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def host(server_url, playwright) -> HostPage:
    browser, ctx = host_browser_ctx(server_url, playwright)
    page = ctx.new_page()
    page.goto("/host")
    yield HostPage(page)
    ctx.close()
    browser.close()


def _make_pax_fixture():
    @pytest.fixture()
    def pax(server_url, playwright) -> ParticipantPage:
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(pax_url())
        yield ParticipantPage(page)
        ctx.close()
        browser.close()
    return pax


pax  = _make_pax_fixture()
pax2 = _make_pax_fixture()
pax3 = _make_pax_fixture()


# ---------------------------------------------------------------------------
# Cleanup fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clean_qa(server_url):
    """Clear Q&A state before and after each test that uses it."""
    api(server_url, "post", "/api/qa/clear")
    yield
    api(server_url, "post", "/api/qa/clear")


@pytest.fixture(autouse=False)
def clean_codereview(server_url):
    """Clear code review state before and after each test that uses it."""
    api(server_url, "delete", "/api/codereview")
    yield
    api(server_url, "delete", "/api/codereview")


@pytest.fixture(autouse=False)
def clean_wordcloud(server_url):
    """Clear word cloud state before and after each test that uses it."""
    api(server_url, "post", "/api/wordcloud/clear")
    yield
    api(server_url, "post", "/api/wordcloud/clear")


@pytest.fixture(autouse=False)
def clean_scores(server_url):
    """Reset all scores before and after each test that uses it."""
    api(server_url, "delete", "/api/scores")
    yield
    api(server_url, "delete", "/api/scores")


@pytest.fixture(autouse=False)
def clean_all(server_url):
    """Clear all activity state."""
    api(server_url, "post", "/api/qa/clear")
    api(server_url, "delete", "/api/codereview")
    api(server_url, "post", "/api/wordcloud/clear")
    api(server_url, "delete", "/api/scores")
    api(server_url, "post", "/api/activity", json={"activity": "none"})
    yield
    api(server_url, "post", "/api/qa/clear")
    api(server_url, "delete", "/api/codereview")
    api(server_url, "post", "/api/wordcloud/clear")
    api(server_url, "delete", "/api/scores")
    api(server_url, "post", "/api/activity", json={"activity": "none"})
