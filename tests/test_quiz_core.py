"""Unit tests for quiz_core.py — config, transcription parsing, validation, HTTP helpers."""
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import quiz_core
from quiz_core import (
    find_session_folder,
    load_secrets_env,
    _parse_vtt,
    _parse_srt,
    _parse_txt,
    _parse_raw_response,
    _validate_quiz,
    _ts_to_seconds,
    load_transcription_files,
    extract_last_n_minutes,
    extract_text_for_time_window,
    read_session_notes,
    _request_json,
    _get_json,
    post_poll,
    open_poll,
    post_status,
    generate_quiz,
    refine_quiz,
    Config,
    print_quiz,
    search_materials,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_folder(base: Path, name: str) -> Path:
    p = base / name
    p.mkdir()
    return p


def _make_config(tmp_path, **overrides):
    defaults = dict(
        folder=tmp_path, minutes=30, server_url="http://localhost:8000",
        api_key="test-key", model="test-model", dry_run=False,
        host_username="host", host_password="pass",
    )
    defaults.update(overrides)
    return Config(**defaults)


# ── find_session_folder ───────────────────────────────────────────────

class TestFindSessionFolder:
    def test_single_day(self, tmp_path):
        folder = _make_folder(tmp_path, "2026-03-19 CleanCode@acme")
        notes = folder / "notes.txt"
        notes.write_text("agenda")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, sn = find_session_folder(date(2026, 3, 19))
        assert sf == folder
        assert sn == notes

    def test_no_match(self, tmp_path):
        _make_folder(tmp_path, "2026-03-19 Workshop")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, sn = find_session_folder(date(2026, 3, 20))
        assert sf is None and sn is None

    def test_multi_day_dd(self, tmp_path):
        folder = _make_folder(tmp_path, "2026-03-18..21 Workshop")
        (folder / "notes.txt").write_text("x")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, sn = find_session_folder(date(2026, 3, 20))
        assert sf == folder

    def test_multi_day_mm_dd(self, tmp_path):
        folder = _make_folder(tmp_path, "2026-03-30..04-02 Workshop")
        (folder / "notes.txt").write_text("x")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, sn = find_session_folder(date(2026, 4, 1))
        assert sf == folder

    def test_no_notes(self, tmp_path):
        _make_folder(tmp_path, "2026-03-19 Workshop")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, sn = find_session_folder(date(2026, 3, 19))
        assert sf is not None and sn is None

    def test_missing_folder(self):
        os.environ["SESSIONS_FOLDER"] = "/nonexistent/xyz"
        sf, sn = find_session_folder(date(2026, 3, 19))
        assert sf is None and sn is None

    def test_latest_start_wins(self, tmp_path):
        _make_folder(tmp_path, "2026-03-18..20 Workshop")
        f2 = _make_folder(tmp_path, "2026-03-19 Workshop")
        (f2 / "notes.txt").write_text("b")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, _ = find_session_folder(date(2026, 3, 19))
        assert sf == f2

    def test_invalid_end_date_skipped(self, tmp_path):
        _make_folder(tmp_path, "2026-03-19..32 Workshop")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        sf, _ = find_session_folder(date(2026, 3, 19))
        assert sf is None

    def test_most_recent_txt(self, tmp_path):
        folder = _make_folder(tmp_path, "2026-03-19 Workshop")
        old = folder / "old.txt"
        new = folder / "new.txt"
        old.write_text("old")
        time.sleep(0.01)
        new.write_text("new")
        os.environ["SESSIONS_FOLDER"] = str(tmp_path)
        _, sn = find_session_folder(date(2026, 3, 19))
        assert sn == new


# ── load_secrets_env ──────────────────────────────────────────────────

class TestLoadSecretsEnv:
    def test_loads_env(self, tmp_path, monkeypatch):
        secrets = tmp_path / ".training-assistants-secrets.env"
        secrets.write_text("TEST_KEY_ABC=hello\n# comment\n\nTEST_KEY_DEF=world\n")
        monkeypatch.setenv("TRAINING_ASSISTANTS_SECRETS_FILE", str(secrets))
        monkeypatch.delenv("TEST_KEY_ABC", raising=False)
        monkeypatch.delenv("TEST_KEY_DEF", raising=False)
        load_secrets_env()
        assert os.environ.get("TEST_KEY_ABC") == "hello"
        assert os.environ.get("TEST_KEY_DEF") == "world"

    def test_missing_file(self, monkeypatch):
        monkeypatch.setenv("TRAINING_ASSISTANTS_SECRETS_FILE", "/tmp/does-not-exist.env")
        load_secrets_env()  # should not raise


# ── Transcription parsing ─────────────────────────────────────────────

SAMPLE_VTT = """WEBVTT

00:01:05.000 --> 00:01:10.000
Hello world first segment.

00:02:30.000 --> 00:02:35.000
Second segment here.
With continuation line.
"""

SAMPLE_SRT = """1
00:01:05,000 --> 00:01:10,000
Hello from SRT.

2
00:02:30,000 --> 00:02:35,000
Second SRT segment.
"""

SAMPLE_TXT = """[00:01:05.00] Speaker:\tHello from TXT.
[00:02:30.00] Speaker:\tSecond line.
plain text without timestamp
"""

SAMPLE_TXT2 = """[ 00:01:05.00 ] Hello alternate format.
[ 00:02:30.00 ] Second alternate.
"""


class TestTranscriptionParsing:
    def test_ts_to_seconds(self):
        assert _ts_to_seconds(1, 30, 15) == 5415
        assert _ts_to_seconds(0, 0, 0) == 0
        assert _ts_to_seconds(None, 2, 30) == 150

    def test_parse_vtt(self):
        entries = _parse_vtt(SAMPLE_VTT)
        assert len(entries) == 2
        assert entries[0][0] == 65.0  # 1:05
        assert "first segment" in entries[0][1]
        assert entries[1][0] == 150.0  # 2:30
        assert "continuation" in entries[1][1]

    def test_parse_vtt_empty(self):
        assert _parse_vtt("") == []
        assert _parse_vtt("WEBVTT\n\n") == []

    def test_parse_srt(self):
        entries = _parse_srt(SAMPLE_SRT)
        assert len(entries) == 2
        assert entries[0][0] == 65.0
        assert "SRT" in entries[0][1]

    def test_parse_srt_empty(self):
        assert _parse_srt("") == []

    def test_parse_txt(self):
        entries = _parse_txt(SAMPLE_TXT)
        assert len(entries) == 3
        assert entries[0][0] == 65.0
        assert entries[2][0] is None  # plain text
        assert "without timestamp" in entries[2][1]

    def test_parse_txt_alternate(self):
        entries = _parse_txt(SAMPLE_TXT2)
        assert len(entries) == 2
        assert entries[0][0] == 65.0
        assert "alternate" in entries[0][1]

    def test_parse_txt_with_date_prefix(self):
        entries = _parse_txt("[2026-03-23 14:30:45.00] Speaker:\tHello with date.")
        assert len(entries) == 1
        assert entries[0][0] == 14 * 3600 + 30 * 60 + 45
        assert "Hello with date" in entries[0][1]

    def test_parse_txt_empty(self):
        assert _parse_txt("") == []
        assert _parse_txt("\n\n") == []


class TestLoadTranscriptionFiles:
    def test_loads_txt(self, tmp_path):
        (tmp_path / "2026-03-25 transcription.txt").write_text("[10:05] Victor: hello\n[10:06] Ana: hi\n")
        entries = load_transcription_files(tmp_path)
        assert len(entries) == 2

    def test_picks_most_recent(self, tmp_path):
        (tmp_path / "2026-03-25 transcription.txt").write_text("[10:00] old")
        time.sleep(0.01)
        (tmp_path / "2026-03-26 transcription.txt").write_text("[11:00] new")
        entries = load_transcription_files(tmp_path)
        assert len(entries) == 1
        assert entries[0][0] == 11 * 3600
        assert entries[0][1] == "new"

    def test_no_files_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            load_transcription_files(tmp_path)

    def test_no_normalized_files_exits(self, tmp_path):
        (tmp_path / "20260325 1000 Transcription.txt").write_text("[00:00:01.00] Speaker:\traw")
        with pytest.raises(SystemExit):
            load_transcription_files(tmp_path)

    def test_prefers_normalized_txt_when_present(self, tmp_path):
        (tmp_path / "20260325 1000 Transcription.txt").write_text("[00:00:01.00] Speaker:\traw")
        (tmp_path / "2026-03-25 transcription.txt").write_text("[10:05] Victor: normalized")
        entries = load_transcription_files(tmp_path)
        assert len(entries) == 1
        assert entries[0][0] == 10 * 3600 + 5 * 60
        assert entries[0][1] == "Victor: normalized"

    def test_normalized_since_date_loads_multiple_days(self, tmp_path):
        (tmp_path / "2026-03-25 transcription.txt").write_text("[23:59] A: day1")
        (tmp_path / "2026-03-26 transcription.txt").write_text("[00:01] B: day2")
        entries = load_transcription_files(tmp_path, since_date=date(2026, 3, 25))
        assert len(entries) == 2
        assert entries[0][0] == 23 * 3600 + 59 * 60
        assert entries[1][0] == 86400 + 60


class TestExtractLastNMinutes:
    def test_timed_extraction(self):
        entries = [(0.0, "early"), (300.0, "middle"), (600.0, "late")]
        text = extract_last_n_minutes(entries, 5)
        assert "late" in text
        assert "early" not in text

    def test_untimed_fallback(self):
        entries = [(None, "word " * 100)]
        text = extract_last_n_minutes(entries, 1)
        assert len(text) > 0

    def test_caps_at_max(self):
        entries = [(0.0, "x" * 100_000)]
        text = extract_last_n_minutes(entries, 999)
        assert len(text) <= quiz_core.MAX_CHARS_TO_CLAUDE


class TestReadSessionNotes:
    def test_reads_notes(self, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("Session agenda here")
        cfg = _make_config(tmp_path, session_notes=notes)
        assert read_session_notes(cfg) == "Session agenda here"

    def test_no_notes(self, tmp_path):
        cfg = _make_config(tmp_path, session_notes=None)
        assert read_session_notes(cfg) == ""

    def test_truncates_long(self, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("x" * 30_000)
        cfg = _make_config(tmp_path, session_notes=notes)
        result = read_session_notes(cfg)
        assert len(result) <= quiz_core.MAX_SESSION_NOTES_CHARS

    def test_missing_file(self, tmp_path):
        cfg = _make_config(tmp_path, session_notes=tmp_path / "gone.txt")
        assert read_session_notes(cfg) == ""


# ── Quiz validation ───────────────────────────────────────────────────

class TestParseRawResponse:
    def test_plain_json(self):
        raw = '{"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}'
        result = _parse_raw_response(raw)
        assert result["question"] == "Q?"

    def test_markdown_fences(self):
        raw = '```json\n{"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}\n```'
        result = _parse_raw_response(raw)
        assert result["question"] == "Q?"

    def test_embedded_json(self):
        raw = 'Here is the result:\n{"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}\nDone.'
        result = _parse_raw_response(raw)
        assert result["question"] == "Q?"

    def test_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_raw_response("not json at all")


class TestValidateQuiz:
    def _valid_quiz(self):
        return {"question": "Q?", "options": ["A", "B", "C"], "correct_indices": [1]}

    def test_valid_passes(self):
        _validate_quiz(self._valid_quiz(), "")

    def test_missing_question(self):
        q = self._valid_quiz()
        q["question"] = ""
        with pytest.raises(RuntimeError, match="question"):
            _validate_quiz(q, "")

    def test_too_few_options(self):
        q = self._valid_quiz()
        q["options"] = ["A"]
        with pytest.raises(RuntimeError, match="options"):
            _validate_quiz(q, "")

    def test_too_many_options(self):
        q = self._valid_quiz()
        q["options"] = [f"O{i}" for i in range(9)]
        with pytest.raises(RuntimeError, match="options"):
            _validate_quiz(q, "")

    def test_empty_option(self):
        q = self._valid_quiz()
        q["options"][1] = ""
        with pytest.raises(RuntimeError, match="option"):
            _validate_quiz(q, "")

    def test_invalid_index(self):
        q = self._valid_quiz()
        q["correct_indices"] = [5]
        with pytest.raises(RuntimeError, match="correct_indices"):
            _validate_quiz(q, "")

    def test_empty_correct_indices(self):
        q = self._valid_quiz()
        q["correct_indices"] = []
        with pytest.raises(RuntimeError, match="correct_indices"):
            _validate_quiz(q, "")

    def test_multi_correct(self):
        q = self._valid_quiz()
        q["correct_indices"] = [0, 2]
        _validate_quiz(q, "")  # should pass


# ── print_quiz ────────────────────────────────────────────────────────

class TestPrintQuiz:
    def test_prints_without_error(self, capsys):
        quiz = {"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}
        print_quiz(quiz)
        out = capsys.readouterr().out
        assert "Q?" in out
        assert "✅" in out

    def test_multi_correct(self, capsys):
        quiz = {"question": "Q?", "options": ["A", "B", "C"], "correct_indices": [0, 2]}
        print_quiz(quiz)
        out = capsys.readouterr().out
        assert "multiple" in out.lower()

    def test_source_shown(self, capsys):
        quiz = {"question": "Q?", "options": ["A", "B"], "correct_indices": [0], "source": "Book", "page": "42"}
        print_quiz(quiz)
        out = capsys.readouterr().out
        assert "Book" in out and "42" in out


# ── HTTP helpers ──────────────────────────────────────────────────────

class TestRequestJson:
    @patch("quiz_core.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _request_json("http://test/api", {"data": 1}, username="u", password="p")
        assert result == {"ok": True}

    @patch("quiz_core.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("http://test", 401, "Unauthorized", {}, None)
        with pytest.raises(RuntimeError, match="401"):
            _request_json("http://test/api", {})

    @patch("quiz_core.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        with pytest.raises(RuntimeError, match="timed out"):
            _request_json("http://test/api", {})

    @patch("quiz_core.urllib.request.urlopen")
    def test_url_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(RuntimeError, match="Cannot reach"):
            _request_json("http://test/api", {})

    @patch("quiz_core.urllib.request.urlopen")
    def test_invalid_json_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        with pytest.raises(RuntimeError, match="Invalid JSON"):
            _request_json("http://test/api", {})


class TestGetJson:
    @patch("quiz_core.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _get_json("http://test/api", username="u", password="p")
        assert result == {"status": "ok"}

    @patch("quiz_core.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("http://test", 500, "ISE", {}, None)
        with pytest.raises(RuntimeError, match="500"):
            _get_json("http://test/api")


# ── search_materials ──────────────────────────────────────────────────

class TestSearchMaterials:
    def test_fallback_when_no_rag(self):
        with patch.dict("sys.modules", {"daemon.rag": None}):
            with patch("quiz_core.search_materials") as mock_sm:
                mock_sm.side_effect = quiz_core.search_materials.__wrapped__ if hasattr(quiz_core.search_materials, '__wrapped__') else None
        # The actual function tries dynamic import
        results = search_materials("test")
        assert isinstance(results, list)
        assert len(results) > 0


# ── generate_quiz ─────────────────────────────────────────────────────

class TestGenerateQuiz:
    def test_simple_generation(self, tmp_path):
        cfg = _make_config(tmp_path)
        quiz_json = '{"question": "Q?", "options": ["A", "B", "C"], "correct_indices": [1]}'

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = quiz_json
        mock_response.content = [mock_block]

        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            result = generate_quiz("some transcript", cfg)
            assert result["question"] == "Q?"
            assert result["correct_indices"] == [1]

    def test_tool_use_flow(self, tmp_path):
        cfg = _make_config(tmp_path)

        # First response: tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_1"
        tool_block.input = {"query": "test query"}
        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [tool_block]

        # Second response: text
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '{"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}'
        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]

        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = [resp1, resp2]
            with patch("quiz_core.search_materials", return_value=[{"content": "test"}]):
                result = generate_quiz("transcript", cfg)
                assert result["question"] == "Q?"

    def test_api_error(self, tmp_path):
        import anthropic
        cfg = _make_config(tmp_path)
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = anthropic.APIError(
                message="Test error", request=MagicMock(), body=None
            )
            with pytest.raises(RuntimeError, match="Claude API error"):
                generate_quiz("text", cfg)

    def test_invalid_json_response(self, tmp_path):
        cfg = _make_config(tmp_path)
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "not json at all"
        mock_response.content = [mock_block]
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            with pytest.raises(RuntimeError, match="invalid JSON"):
                generate_quiz("text", cfg)


# ── refine_quiz ───────────────────────────────────────────────────────

class TestRefineQuiz:
    def _base_quiz(self):
        return {"question": "Q?", "options": ["A", "B", "C"], "correct_indices": [1]}

    def test_refine_option(self, tmp_path):
        cfg = _make_config(tmp_path)
        updated = '{"question": "Q?", "options": ["A", "New B", "C"], "correct_indices": [1]}'
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=updated)]
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            result = refine_quiz(self._base_quiz(), "opt1", "transcript", cfg)
            assert result["options"][1] == "New B"

    def test_refine_question(self, tmp_path):
        cfg = _make_config(tmp_path)
        updated = '{"question": "New Q?", "options": ["X", "Y"], "correct_indices": [0]}'
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=updated)]
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            result = refine_quiz(self._base_quiz(), "question", "transcript", cfg)
            assert result["question"] == "New Q?"

    def test_refine_invalid_json_returns_original(self, tmp_path):
        cfg = _make_config(tmp_path)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="garbage")]
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            result = refine_quiz(self._base_quiz(), "opt0", "transcript", cfg)
            assert result == self._base_quiz()  # fallback to original

    def test_refine_api_error(self, tmp_path):
        import anthropic
        cfg = _make_config(tmp_path)
        with patch("quiz_core.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = anthropic.APIError(
                message="err", request=MagicMock(), body=None
            )
            with pytest.raises(RuntimeError):
                refine_quiz(self._base_quiz(), "opt0", "transcript", cfg)


# ── post_poll / open_poll / post_status ───────────────────────────────

class TestServerHelpers:
    @patch("quiz_core._post_json")
    def test_post_poll(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        quiz = {"question": "Q?", "options": ["A", "B"], "correct_indices": [0]}
        post_poll(quiz, cfg)
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][1]
        assert payload["question"] == "Q?"
        assert payload["multi"] is False

    @patch("quiz_core._post_json")
    def test_post_poll_multi(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        quiz = {"question": "Q?", "options": ["A", "B", "C"], "correct_indices": [0, 2]}
        post_poll(quiz, cfg)
        payload = mock_post.call_args[0][1]
        assert payload["multi"] is True

    @patch("quiz_core._post_json")
    def test_post_poll_with_source(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        quiz = {"question": "Q?", "options": ["A", "B"], "correct_indices": [0], "source": "Book", "page": "42"}
        post_poll(quiz, cfg)
        payload = mock_post.call_args[0][1]
        assert "Source: Book" in payload["question"]

    @patch("quiz_core._put_json")
    def test_open_poll(self, mock_put, tmp_path):
        cfg = _make_config(tmp_path)
        open_poll(cfg)
        mock_put.assert_called_once()
        payload = mock_put.call_args[0][1]
        assert payload["open"] is True

    @patch("quiz_core._post_json")
    def test_post_status(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        post_status("generating", "Working...", cfg)
        mock_post.assert_called_once()

    @patch("quiz_core._post_json")
    def test_post_status_with_session(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        post_status("idle", "Ready", cfg, session_folder="/path", session_notes="notes.txt")
        payload = mock_post.call_args[0][1]
        assert payload["session_folder"] == "/path"

    @patch("quiz_core._post_json")
    def test_post_status_with_slides(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        post_status("idle", "Ready", cfg, slides=[{"name": "Deck", "url": "https://cdn.example.com/deck.pdf"}])
        payload = mock_post.call_args[0][1]
        assert "slides" in payload
        assert payload["slides"][0]["name"] == "Deck"

    @patch("quiz_core._post_json")
    def test_post_status_error_swallowed(self, mock_post, tmp_path):
        cfg = _make_config(tmp_path)
        mock_post.side_effect = RuntimeError("connection refused")
        post_status("idle", "msg", cfg)  # should not raise


# ── extract_text_for_time_window ──────────────────────────────────────

class TestTimeWindowExtraction:
    def test_basic_window(self):
        entries = [
            (3600 * 9, "morning talk"),       # 09:00
            (3600 * 12, "lunch topic"),        # 12:00
            (3600 * 13, "afternoon talk"),     # 13:00
        ]
        text = extract_text_for_time_window(
            entries,
            start_ts=3600 * 9,
            end_ts=3600 * 17,
            exclude_ranges=[(3600 * 12, 3600 * 13)],
        )
        assert "morning talk" in text
        assert "afternoon talk" in text
        assert "lunch topic" not in text

    def test_no_exclusions(self):
        entries = [(3600 * 10, "hello"), (3600 * 11, "world")]
        text = extract_text_for_time_window(entries, start_ts=3600 * 9, end_ts=3600 * 12)
        assert "hello" in text
        assert "world" in text

    def test_empty_when_all_excluded(self):
        entries = [(3600 * 12, "lunch only")]
        text = extract_text_for_time_window(
            entries, start_ts=3600 * 9, end_ts=3600 * 17,
            exclude_ranges=[(3600 * 11, 3600 * 13)],
        )
        assert text == ""

    def test_none_timestamps_skipped(self):
        entries = [(None, "no ts"), (3600 * 10, "has ts")]
        text = extract_text_for_time_window(entries, start_ts=3600 * 9)
        assert "has ts" in text
        assert "no ts" not in text
