import pytest

import daemon.http as quiz_core


class _Resp:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_post_json_wraps_invalid_json_as_runtime_error(monkeypatch):
    monkeypatch.setattr(
        quiz_core.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Resp(b"[] not object"),
    )

    with pytest.raises(RuntimeError, match="Invalid JSON response from server"):
        quiz_core._post_json("http://example.test/api", {"ok": True})
