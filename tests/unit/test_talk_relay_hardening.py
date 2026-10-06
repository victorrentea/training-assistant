"""Relay hardening found while load- and abuse-testing the conference talk mode.

- The slide cache file is replaced atomically: phones range-read it during a talk.
- Garbage frames from a participant socket are ignored, not fatal.
- Slide PDFs are streamed in big chunks (CPU per phone on the single worker).
"""
import io
import time

import pytest
from fastapi.testclient import TestClient

import railway.features.slides.cache as cache_mod
from railway.app import app
from railway.features.slides.router import _SlideFileResponse
from railway.shared.state import state


@pytest.fixture(autouse=True)
def clean_state():
    import railway.shared.messaging as _msg
    _msg._participant_update_throttle._last_run = 0.0
    _msg._participant_update_throttle._pending_handle = None
    state.reset()
    state.session_id = "talk01"
    yield
    state.reset()


def test_cached_pdf_is_replaced_atomically(tmp_path, monkeypatch):
    dest = tmp_path / "deck.pdf"
    dest.write_bytes(b"%PDF-old")
    reader = dest.open("rb")  # a phone mid range-read keeps the old inode

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cache_mod.urllib.request, "urlopen", lambda *a, **k: _Resp(b"%PDF-new-content"))
    assert cache_mod._download_pdf_sync("https://example.invalid/x.pdf", dest) == len(b"%PDF-new-content")
    assert dest.read_bytes() == b"%PDF-new-content"
    assert reader.read() == b"%PDF-old"  # never saw a truncated or mixed file
    reader.close()
    assert [p.name for p in tmp_path.iterdir()] == ["deck.pdf"]  # no .part left behind


def test_garbage_frames_do_not_drop_a_participant_socket():
    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/garbage-sender") as ws:
        assert ws.receive_json().get("type") == "active_participants_count_updated"
        ws.send_text("not json at all")
        ws.send_text("[1, 2, 3]")
        ws.send_text('"a string"')
        ws.send_text('{"type": "still-alive"}')
        time.sleep(0.3)  # let the server process the frames
        # Still connected and registered after the garbage.
        assert "garbage-sender" in state.participants


def test_slide_pdfs_stream_in_big_chunks():
    assert _SlideFileResponse.chunk_size >= 256 * 1024
