"""Railway proxy worker: shared keep-alive client, enough workers, guards intact."""
import json

import httpx
import pytest

from daemon import proxy_handler
from daemon.proxy_handler import RAILWAY_PROXY_MARKER, _process_proxy_request


class _WsClient:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, msg):
        self.sent.append(msg)
        return True


class _RecordingClient:
    """Stands in for the shared httpx.Client; answers 200 and records calls."""

    def __init__(self):
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return httpx.Response(
            200,
            json={"ok": True},
            headers={"x-write-back-events": json.dumps([{"type": "broadcast", "event": {}}])},
        )


@pytest.fixture
def client(monkeypatch):
    rec = _RecordingClient()
    monkeypatch.setattr(proxy_handler, "_client", rec)

    def no_per_call_client(*args, **kwargs):
        raise AssertionError("a fresh connection per call: use the shared client")

    monkeypatch.setattr(httpx, "request", no_per_call_client)
    return rec


def _req(path="/api/participant/emoji/reaction", headers=None, **extra):
    return {
        "id": "r1",
        "method": "POST",
        "path": path,
        "body": '{"emoji":"x"}',
        "headers": headers or {},
        **extra,
    }


def test_shared_pooled_client_is_configured_for_loopback():
    c = proxy_handler._client
    assert isinstance(c, httpx.Client)
    assert c._trust_env is False  # loopback must never go through an env proxy
    assert proxy_handler.PROXY_WORKERS >= 32
    assert proxy_handler._executor._max_workers == proxy_handler.PROXY_WORKERS


def test_shared_client_never_replays_one_participants_cookie_to_another(monkeypatch):
    """A Set-Cookie answered to participant A must not ride along on B's call."""
    seen_cookie_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(200, json={}, headers={"set-cookie": "sid=from-a; Path=/"})

    monkeypatch.setattr(proxy_handler._client, "_transport", httpx.MockTransport(handler))
    _process_proxy_request(_req(headers={"X-Participant-ID": "a"}), _WsClient())
    _process_proxy_request(_req(headers={"X-Participant-ID": "b"}), _WsClient())
    assert seen_cookie_headers == [None, None]
    assert len(proxy_handler._client.cookies.jar) == 0


def test_every_call_reuses_the_one_shared_client(client):
    ws = _WsClient()
    for _ in range(3):
        _process_proxy_request(_req(), ws)
    assert len(client.calls) == 3
    responses = [m for m in ws.sent if m["type"] == "proxy_response"]
    assert [r["status"] for r in responses] == [200, 200, 200]
    # write-back events still go out before the proxy_response
    assert ws.sent[0]["type"] == "broadcast"


def test_timeout_follows_railway_plus_buffer(client):
    _process_proxy_request(_req(timeout=15), _WsClient())
    _process_proxy_request(_req(), _WsClient())
    assert [c["timeout"] for c in client.calls] == [20.0, 10.0]


def test_marker_stamped_and_hop_by_hop_headers_dropped(client):
    _process_proxy_request(_req(headers={
        "Connection": "close",
        "Keep-Alive": "timeout=5",
        "Transfer-Encoding": "chunked",
        "X-Participant-ID": "p1",
        RAILWAY_PROXY_MARKER: "0",  # a forged marker is replaced, never trusted
    }), _WsClient())
    sent = {k.lower(): v for k, v in client.calls[0]["headers"].items()}
    assert sent[RAILWAY_PROXY_MARKER] == "1"
    assert sent["x-participant-id"] == "p1"
    assert not {"connection", "keep-alive", "transfer-encoding"} & sent.keys()


def test_traversal_is_still_rejected_before_any_call(client):
    ws = _WsClient()
    _process_proxy_request(_req(path="/api/participant/../host-machine/claim-trainer"), ws)
    assert client.calls == []
    assert ws.sent[-1]["status"] == 400


def test_local_failure_answers_502(monkeypatch):
    class _Down:
        def request(self, **kwargs):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(proxy_handler, "_client", _Down())
    ws = _WsClient()
    _process_proxy_request(_req(), ws)
    assert ws.sent[-1]["type"] == "proxy_response" and ws.sent[-1]["status"] == 502
