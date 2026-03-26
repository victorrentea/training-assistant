import json, tempfile
from pathlib import Path
from types import SimpleNamespace


def test_load_daemon_state_new_format():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None


def test_load_daemon_state_migrates_old_stack_format():
    """Old {stack:[...]} format is migrated to {main, talk}."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"}
            ]
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None


def test_load_daemon_state_migrates_two_item_stack():
    """Old stack with 2 items: first=main, second=talk."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"},
                {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00"}
            ]
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"]["name"] == "2026-03-25 12:30 talk"


def test_load_daemon_state_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as d:
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result == {"main": None, "talk": None}


def test_save_daemon_state_writes_new_format():
    with tempfile.TemporaryDirectory() as d:
        from training_daemon import _save_daemon_state
        _save_daemon_state(Path(d), {
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        })
        data = json.loads((Path(d) / "daemon_state.json").read_text())
        assert "main" in data
        assert "stack" not in data
        assert data["main"]["name"] == "2026-03-25 WS"


# ── Issue 2: status "ended" filtering ────────────────────────────────────────

def test_daemon_state_to_stack_filters_ended_main():
    """Main session with status 'ended' should produce an empty stack."""
    from training_daemon import _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "ended"},
        "talk": None,
    })
    assert result == []


def test_daemon_state_to_stack_filters_ended_talk_keeps_main():
    """Talk session with status 'ended' is discarded; main is kept."""
    from training_daemon import _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "ended"},
    })
    assert len(result) == 1
    assert result[0]["name"] == "2026-03-25 WS"


def test_daemon_state_to_stack_active_sessions_included():
    """Active and paused sessions are included in the stack."""
    from training_daemon import _daemon_state_to_stack
    result = _daemon_state_to_stack({
        "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "paused"},
    })
    assert len(result) == 2


# ── Issue 1: startup restore includes session_state.json ─────────────────────

def test_sync_session_includes_session_state_when_file_exists():
    """When session_state.json exists in the session folder, _sync_session_to_server
    is called with the contents in the payload."""
    from unittest.mock import patch, call
    import training_daemon

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

        def fake_post_json(url, payload, username, password):
            captured["payload"] = payload

        with patch.object(training_daemon, "_post_json", fake_post_json):
            training_daemon._sync_session_to_server(
                type("C", (), {
                    "server_url": "http://test",
                    "host_username": "u",
                    "host_password": "p",
                })(),
                stack,
                [],
                session_state_data,
            )

        assert "session_state" in captured["payload"]
        assert captured["payload"]["session_state"]["mode"] == "workshop"


def test_sync_session_no_session_state_key_when_none():
    """When session_state is None, the payload should not include the key."""
    from unittest.mock import patch
    import training_daemon

    captured = {}

    def fake_post_json(url, payload, username, password):
        captured["payload"] = payload

    with patch.object(training_daemon, "_post_json", fake_post_json):
        training_daemon._sync_session_to_server(
            type("C", (), {
                "server_url": "http://test",
                "host_username": "u",
                "host_password": "p",
            })(),
            [],
            [],
            None,
        )

    assert "session_state" not in captured["payload"]


def test_normalize_slides_manifest_accepts_slug_mapping():
    from training_daemon import _normalize_slides_manifest
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
    from training_daemon import _load_slides_manifest
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


def test_parse_powerpoint_probe_output_active_state():
    from training_daemon import _parse_powerpoint_probe_output

    parsed = _parse_powerpoint_probe_output("Architecture deck\t12\n")
    assert parsed == {"presentation": "Architecture deck", "slide": 12}


def test_parse_powerpoint_probe_output_handles_no_presentation_tokens():
    from training_daemon import _parse_powerpoint_probe_output

    assert _parse_powerpoint_probe_output("__NO_PPT__") is None
    assert _parse_powerpoint_probe_output("__NO_PRESENTATION__") is None
    assert _parse_powerpoint_probe_output("") is None


def test_parse_powerpoint_probe_output_missing_value_defaults_to_slide_one():
    from training_daemon import _parse_powerpoint_probe_output

    parsed = _parse_powerpoint_probe_output("Deck A\tmissing value")
    assert parsed == {"presentation": "Deck A", "slide": 1}


def test_probe_powerpoint_state_success(monkeypatch):
    import training_daemon

    monkeypatch.setattr(
        training_daemon.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Deck A\t7\n", stderr=""),
    )

    state, error = training_daemon._probe_powerpoint_state()
    assert error is None
    assert state == {"presentation": "Deck A", "slide": 7}


def test_probe_powerpoint_state_returns_error_on_nonzero_exit(monkeypatch):
    import training_daemon

    monkeypatch.setattr(
        training_daemon.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Execution error"),
    )

    state, error = training_daemon._probe_powerpoint_state()
    assert state is None
    assert error == "Execution error"


def test_resolve_presentation_slide_target_uses_catalog_mapping(tmp_path):
    from training_daemon import _resolve_presentation_slide_target

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
    from training_daemon import _resolve_presentation_slide_target

    target = _resolve_presentation_slide_target(
        presentation_name="Unmapped Deck.pptx",
        server_url="http://localhost:8000",
        catalog_file=tmp_path / "missing-catalog.json",
    )
    assert target["slug"] == "unmapped-deck"
    assert target["url"] == "http://localhost:8000/api/slides/file/unmapped-deck"
    assert target["matched"] is False


def test_sync_powerpoint_slide_unknown_presentation_alerts_once(monkeypatch):
    import training_daemon

    training_daemon._PPT_UNMAPPED_PRESENTATIONS_ALERTED.clear()
    calls = {"delete": 0, "beep": 0, "status": []}

    monkeypatch.setattr(
        training_daemon,
        "_resolve_presentation_slide_target",
        lambda **kwargs: {
            "slug": "unknown-deck",
            "url": "http://localhost:8000/api/slides/file/unknown-deck",
            "matched": False,
        },
    )

    def _fake_delete(*args, **kwargs):
        calls["delete"] += 1

    def _fake_beep():
        calls["beep"] += 1

    def _fake_post(url, payload, username, password):
        calls["status"].append({"url": url, "payload": payload})
        return {"ok": True}

    monkeypatch.setattr(training_daemon, "_delete_with_basic_auth", _fake_delete)
    monkeypatch.setattr(training_daemon, "_beep_local", _fake_beep)
    monkeypatch.setattr(training_daemon, "_post_json", _fake_post)

    cfg = SimpleNamespace(
        server_url="http://localhost:8000",
        host_username="host",
        host_password="secret",
    )
    ppt_state = {"presentation": "Unknown Deck.pptx", "slide": 4}

    training_daemon._sync_powerpoint_slide_to_server(cfg, None, ppt_state)
    training_daemon._sync_powerpoint_slide_to_server(cfg, None, ppt_state)

    assert calls["delete"] == 2
    assert calls["beep"] == 1
    assert len(calls["status"]) == 1
    assert calls["status"][0]["url"].endswith("/api/quiz-status")
    assert calls["status"][0]["payload"]["status"] == "error"
    assert "Presentation inaccessible for participants." in calls["status"][0]["payload"]["message"]
