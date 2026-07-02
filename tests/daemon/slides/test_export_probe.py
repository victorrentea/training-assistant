"""Hermetic tests for daemon.slides.export_probe.

Covers (1) the HEAD health decision with urlopen mocked, and (2) the
grace→retry→alarm→auto-clear scheduler with shrunk timings and a stubbed
add-on bridge — no network, no real sleeps beyond a few ms.
"""
import io
import time
import urllib.error

import pytest

from daemon.slides import export_probe as ep


class _FakeResp:
    def __init__(self, status, content_type):
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_returning(status, content_type):
    def _fn(req, timeout=0, context=None):
        return _FakeResp(status, content_type)
    return _fn


def _urlopen_raising_http(code):
    def _fn(req, timeout=0, context=None):
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b""))
    return _fn


def test_probe_healthy_when_200_pdf(monkeypatch):
    monkeypatch.setattr(ep.urllib.request, "urlopen", _urlopen_returning(200, "application/pdf"))
    healthy, detail = ep.probe_drive_export("http://x")
    assert healthy is True
    assert "200" in detail


def test_probe_unhealthy_when_export_fails_512(monkeypatch):
    monkeypatch.setattr(ep.urllib.request, "urlopen", _urlopen_raising_http(512))
    healthy, detail = ep.probe_drive_export("http://x")
    assert healthy is False
    assert "512" in detail


def test_probe_unhealthy_when_200_but_html(monkeypatch):
    # Google returns a 200 HTML error page in some failure modes — not a PDF.
    monkeypatch.setattr(ep.urllib.request, "urlopen", _urlopen_returning(200, "text/html; charset=utf-8"))
    healthy, _ = ep.probe_drive_export("http://x")
    assert healthy is False


@pytest.fixture
def fast_timings(monkeypatch):
    monkeypatch.setattr(ep, "GRACE_S", 0.01)
    monkeypatch.setattr(ep, "RETRY_INTERVAL_S", 0.01)
    monkeypatch.setattr(ep, "MAX_RETRY_WINDOW_S", 0.03)
    monkeypatch.setattr(ep, "RECHECK_INTERVAL_S", 0.01)


def _wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_scheduler_raises_then_clears(monkeypatch, fast_timings):
    sent: list[dict] = []
    monkeypatch.setattr(ep, "send_pdf_export_alarm", lambda **kw: sent.append(kw) or True)

    state = {"fail": True}
    monkeypatch.setattr(
        ep, "probe_drive_export",
        lambda url, timeout=0: (not state["fail"], "HTTP 512" if state["fail"] else "HTTP 200"),
    )

    ep.schedule_probe("agentic", "Agentic Engineering", "http://x")

    # Persistent failure → alarm raised (failing=True).
    assert _wait_until(lambda: any(m["failing"] for m in sent)), sent
    raised = next(m for m in sent if m["failing"])
    assert raised["deck"] == "Agentic Engineering" and raised["slug"] == "agentic"

    # Recovery → alarm cleared (failing=False).
    state["fail"] = False
    assert _wait_until(lambda: any(not m["failing"] for m in sent)), sent


def test_scheduler_no_alarm_when_healthy(monkeypatch, fast_timings):
    sent: list[dict] = []
    monkeypatch.setattr(ep, "send_pdf_export_alarm", lambda **kw: sent.append(kw) or True)
    monkeypatch.setattr(ep, "probe_drive_export", lambda url, timeout=0: (True, "HTTP 200"))

    ep.schedule_probe("clean-code", "Clean Code", "http://x")
    time.sleep(0.15)
    assert sent == []  # a healthy deck never alarms


def test_newer_change_supersedes_previous_probe(monkeypatch, fast_timings):
    monkeypatch.setattr(ep, "send_pdf_export_alarm", lambda **kw: True)
    monkeypatch.setattr(ep, "probe_drive_export", lambda url, timeout=0: (False, "HTTP 512"))

    ep.schedule_probe("agentic", "Agentic Engineering", "http://x")
    first_cancel = ep._probes["agentic"]
    ep.schedule_probe("agentic", "Agentic Engineering", "http://x")
    assert first_cancel.is_set()  # the superseded probe was cancelled
    assert ep._probes["agentic"] is not first_cancel
