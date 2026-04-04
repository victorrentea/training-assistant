import json, tempfile
from pathlib import Path
from types import SimpleNamespace

from daemon.session_state import GLOBAL_STATE_FILENAME


def test_load_daemon_state_new_format():
    """New format stores only active_session_id."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / GLOBAL_STATE_FILENAME
        f.write_text(json.dumps({"active_session_id": "abc123"}))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["active_session_id"] == "abc123"
        assert "main" not in result
        assert "talk" not in result


def test_load_daemon_state_returns_raw_old_main_talk_format():
    """Old {main, talk} format is returned as-is for caller to migrate."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / GLOBAL_STATE_FILENAME
        f.write_text(json.dumps({
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        }))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None


def test_load_daemon_state_returns_raw_old_stack_format():
    """Old {stack:[...]} format is returned as-is for caller to migrate."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / GLOBAL_STATE_FILENAME
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"},
                {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00"}
            ]
        }))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert "stack" in result
        assert len(result["stack"]) == 2


def test_load_daemon_state_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result == {}


def test_save_daemon_state_writes_active_session_id_only():
    """New format: only active_session_id is persisted to global state."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_daemon_state as _save_daemon_state
        _save_daemon_state(Path(d), {"active_session_id": "abc123"})
        data = json.loads((Path(d) / GLOBAL_STATE_FILENAME).read_text())
        assert data == {"active_session_id": "abc123"}
        assert "main" not in data
        assert "stack" not in data


def test_load_daemon_state_reads_legacy_filename():
    with tempfile.TemporaryDirectory() as d:
        legacy = Path(d) / "daemon_state.json"
        legacy.write_text(json.dumps({"active_session_id": "legacy123"}))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["active_session_id"] == "legacy123"


# ── Session meta I/O ──────────────────────────────────────────────────────────

def test_save_and_load_session_meta():
    from daemon.session_state import save_session_meta, load_session_meta
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d) / "2026-03-25 WS"
        folder.mkdir()
        meta = {
            "session_id": "abc123",
            "started_at": "2026-03-25T09:00:00",
            "paused_intervals": [{"from": "2026-03-25T12:00:00", "to": "2026-03-25T13:00:00", "reason": "lunch"}],
        }
        save_session_meta(folder, meta)
        result = load_session_meta(folder)
        assert result["session_id"] == "abc123"
        assert result["started_at"] == "2026-03-25T09:00:00"
        assert len(result["paused_intervals"]) == 1


def test_load_session_meta_returns_empty_when_no_file():
    from daemon.session_state import load_session_meta
    with tempfile.TemporaryDirectory() as d:
        result = load_session_meta(Path(d) / "missing-folder")
        assert result == {}


def test_find_session_folder_by_id_via_meta(tmp_path):
    from daemon.session_state import save_session_meta, find_session_folder_by_id
    folder = tmp_path / "2026-03-25 WS"
    folder.mkdir()
    save_session_meta(folder, {"session_id": "target-id-123", "started_at": "2026-03-25T09:00:00"})

    result = find_session_folder_by_id(tmp_path, "target-id-123")
    assert result == folder


def test_find_session_folder_by_id_via_session_state(tmp_path):
    from daemon.session_state import find_session_folder_by_id
    folder = tmp_path / "2026-03-25 WS"
    folder.mkdir()
    (folder / "session_state.json").write_text(json.dumps({"session_id": "server-id-456"}))

    result = find_session_folder_by_id(tmp_path, "server-id-456")
    assert result == folder


def test_find_session_folder_by_id_returns_none_when_not_found(tmp_path):
    from daemon.session_state import find_session_folder_by_id
    result = find_session_folder_by_id(tmp_path, "nonexistent-id")
    assert result is None


def test_session_meta_to_stack_with_talk():
    from daemon.session_state import session_meta_to_stack
    meta = {
        "session_id": "abc123",
        "started_at": "2026-03-25T09:00:00",
        "paused_intervals": [],
        "talk": {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "active"},
    }
    stack = session_meta_to_stack(meta, "2026-03-25 WS")
    assert len(stack) == 2
    assert stack[0]["name"] == "2026-03-25 WS"
    assert stack[1]["name"] == "2026-03-25 12:30 talk"


def test_session_meta_to_stack_without_talk():
    from daemon.session_state import session_meta_to_stack
    meta = {"session_id": "abc123", "started_at": "2026-03-25T09:00:00", "paused_intervals": []}
    stack = session_meta_to_stack(meta, "2026-03-25 WS")
    assert len(stack) == 1
    assert stack[0]["name"] == "2026-03-25 WS"


def test_session_meta_to_stack_ignores_ended_talk():
    from daemon.session_state import session_meta_to_stack
    meta = {
        "session_id": "abc123",
        "started_at": "2026-03-25T09:00:00",
        "paused_intervals": [],
        "talk": {"name": "2026-03-25 12:30 talk", "status": "ended"},
    }
    stack = session_meta_to_stack(meta, "2026-03-25 WS")
    assert len(stack) == 1


# ── Issue 2: status "ended" filtering ────────────────────────────────────────

def test_daemon_state_to_stack_filters_ended_main():
    """Main session with status 'ended' should produce an empty stack."""
    from daemon.session_state import daemon_state_to_stack as _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "ended"},
        "talk": None,
    })
    assert result == []


def test_daemon_state_to_stack_filters_ended_talk_keeps_main():
    """Talk session with status 'ended' is discarded; main is kept."""
    from daemon.session_state import daemon_state_to_stack as _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "ended"},
    })
    assert len(result) == 1
    assert result[0]["name"] == "2026-03-25 WS"


def test_daemon_state_to_stack_active_sessions_included():
    """Active and paused sessions are included in the stack."""
    from daemon.session_state import daemon_state_to_stack as _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "paused"},
    })
    assert len(result) == 2


# ── Issue 1: startup restore includes session_state.json ─────────────────────

def test_sync_session_includes_session_state_when_file_exists():
    """When session_state.json exists in the session folder, sync_session_to_server
    is called with the contents in the payload."""
    import daemon.session_state as session_state_mod
    from daemon.session_state import sync_session_to_server

    session_state_data = {"mode": "workshop", "activity": "poll", "token_usage": {}}

    with tempfile.TemporaryDirectory() as d:
        sessions_root = Path(d)
        session_name = "2026-03-25 WS"
        session_folder = sessions_root / session_name
        session_folder.mkdir()
        (session_folder / "session_state.json").write_text(
            json.dumps(session_state_data), encoding="utf-8"
        )

        # Build minimal stack referencing the folder we just created
        stack = [{"name": session_name, "started_at": "2026-03-25T09:00:00", "status": "active"}]

        captured = {}

        class FakeWsClient:
            connected = True
            def send(self, payload):
                captured["payload"] = payload

        original_ws = session_state_mod._ws_client
        session_state_mod._ws_client = FakeWsClient()
        try:
            sync_session_to_server(
                type("C", (), {
                    "server_url": "http://test",
                    "host_username": "u",
                    "host_password": "p",
                })(),
                stack,
                [],
                session_state_data,
            )
        finally:
            session_state_mod._ws_client = original_ws

        # Now sends set_session_id instead of session_sync
        assert captured["payload"]["type"] == "set_session_id"
        assert "session_name" in captured["payload"]


def test_sync_session_no_session_state_key_when_none():
    """When session_state is None, the payload should not include the key."""
    import daemon.session_state as session_state_mod
    from daemon.session_state import sync_session_to_server

    captured = {}

    class FakeWsClient:
        connected = True
        def send(self, payload):
            captured["payload"] = payload

    original_ws = session_state_mod._ws_client
    session_state_mod._ws_client = FakeWsClient()
    try:
        sync_session_to_server(
            type("C", (), {
                "server_url": "http://test",
                "host_username": "u",
                "host_password": "p",
            })(),
            [],
            [],
            None,
        )
    finally:
        session_state_mod._ws_client = original_ws

    assert "session_state" not in captured["payload"]


def test_normalize_slides_manifest_accepts_slug_mapping():
    from daemon.session_state import _normalize_slides_manifest
    slides = _normalize_slides_manifest({
        "slides": {
            "arch-deck": {
                "url": "https://cdn.example.com/arch.pdf",
                "name": "Architecture Deck",
                "updated_at": "2026-03-25T11:00:00+00:00",
            }
        }
    })
    assert len(slides) == 1
    assert slides[0]["slug"] == "arch-deck"
    assert slides[0]["name"] == "Architecture Deck"
    assert slides[0]["url"] == "https://cdn.example.com/arch.pdf"


def test_load_slides_manifest_reads_candidate_file():
    from daemon.session_state import load_slides_manifest as _load_slides_manifest
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "slides_manifest.json").write_text(json.dumps({
            "slides": [
                {"name": "Intro", "url": "https://cdn.example.com/intro.pdf"}
            ]
        }), encoding="utf-8")
        slides = _load_slides_manifest(folder)
        assert len(slides) == 1
        assert slides[0]["slug"] == "intro"
        assert slides[0]["url"] == "https://cdn.example.com/intro.pdf"


def test_resolve_session_folder_prefers_active_stack_folder(tmp_path):
    from daemon.__main__ import _resolve_session_folder_from_state

    sessions_root = tmp_path
    active_folder = sessions_root / "2026-03-29 Active"
    active_folder.mkdir()
    active_notes = active_folder / "active-notes.txt"
    active_notes.write_text("active")

    detected_folder = sessions_root / "2026-03-29 Abc"
    detected_folder.mkdir()
    detected_notes = detected_folder / "detected-notes.txt"
    detected_notes.write_text("detected")

    stack = [{"name": active_folder.name, "started_at": "2026-03-29T10:00:00", "status": "active"}]
    sf, sn, source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_stack=stack,
        detected_folder=detected_folder,
        detected_notes=detected_notes,
    )

    assert sf == active_folder
    assert sn == active_notes
    assert source == "stack"


def test_resolve_presentation_slide_target_uses_catalog_mapping(tmp_path):
    from daemon.__main__ import _resolve_presentation_slide_target

    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "decks": [
            {
                "title": "About Victor",
                "source": "/Users/victorrentea/My Drive/Cursuri/Bio Victor.pptx",
                "target_pdf": "About Victor.pdf",
            }
        ]
    }), encoding="utf-8")

    target = _resolve_presentation_slide_target(
        presentation_name="Bio Victor.pptx",
        server_url="https://interact.victorrentea.ro",
        catalog_file=catalog,
    )
    assert target["slug"] == "about-victor"
    assert target["url"] == "https://interact.victorrentea.ro/api/slides/file/about-victor"
    assert target["matched"] is True


def test_resolve_presentation_slide_target_fallback_when_not_mapped(tmp_path):
    from daemon.__main__ import _resolve_presentation_slide_target

    target = _resolve_presentation_slide_target(
        presentation_name="Unmapped Deck.pptx",
        server_url="http://localhost:8000",
        catalog_file=tmp_path / "missing-catalog.json",
    )
    assert target["slug"] == "unmapped-deck"
    assert target["url"] == "http://localhost:8000/api/slides/file/unmapped-deck"
    assert target["matched"] is False


