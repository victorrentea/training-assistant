"""Tests for the Content-Security-Policy on daemon-served host HTML (fix #11)."""
import pytest
from starlette.testclient import TestClient

from daemon.host_server import _HOST_CSP, create_app


@pytest.fixture
def client():
    app = create_app("https://interact.victorrentea.ro")
    # Loopback Host so the local-access guard admits the request.
    return TestClient(app, headers={"host": "127.0.0.1"})


def test_host_page_sets_csp_header(client):
    r = client.get("/host/abc123")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy") == _HOST_CSP


def test_host_landing_sets_csp_header(client):
    r = client.get("/host")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy") == _HOST_CSP


def test_csp_locks_down_the_dangerous_directives():
    # Defense-in-depth invariants that must hold regardless of CDN allowances.
    assert "object-src 'none'" in _HOST_CSP
    assert "base-uri 'self'" in _HOST_CSP
    assert "frame-ancestors 'none'" in _HOST_CSP
    assert "default-src 'self'" in _HOST_CSP
    # No wildcard script host (external <script src> is restricted to the whitelist).
    assert "script-src" in _HOST_CSP
    assert "script-src * " not in _HOST_CSP


def test_csp_keeps_app_dependencies_working():
    # The audited CDNs + inline usage the host page actually needs must be allowed,
    # so the CSP is not app-breaking.
    assert "'unsafe-inline'" in _HOST_CSP           # inline on* handlers + <style>
    assert "https://cdn.jsdelivr.net" in _HOST_CSP  # d3 / qrcode / opentelemetry
    assert "https://unpkg.com" in _HOST_CSP         # leaflet (js + css)
    assert "https://cdnjs.cloudflare.com" in _HOST_CSP  # highlight.js (js + css)
    assert "img-src 'self' data: blob: https:" in _HOST_CSP  # map tiles / flags / QR
    assert "nominatim.openstreetmap.org" in _HOST_CSP        # client-side geocode


def test_csp_allows_highlightjs_on_both_script_and_style(client):
    """highlight.js ships as a <script> AND a theme <link> from cdnjs — the CSP
    must whitelist cdnjs on BOTH script-src and style-src or code highlighting on
    the host page breaks."""
    directives = {
        part.split(None, 1)[0]: part
        for part in (d.strip() for d in _HOST_CSP.split(";"))
        if part
    }
    assert "https://cdnjs.cloudflare.com" in directives["script-src"]
    assert "https://cdnjs.cloudflare.com" in directives["style-src"]


def test_non_html_responses_have_no_csp(client):
    # The CSP is scoped to the HTML documents, not the JSON API.
    r = client.get("/api/daemon-status")
    assert r.status_code == 200
    assert "content-security-policy" not in {k.lower() for k in r.headers}
