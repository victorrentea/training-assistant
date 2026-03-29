"""Unit tests for daemon/ modules — indexer, summarizer, transcript_timestamps, debate_ai, rag."""
import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════
# daemon/transcript_timestamps.py
# ═══════════════════════════════════════════════════════════════════════
from daemon.transcript.timestamps import (
    infer_template_from_first_line,
    build_timestamp_line,
    append_empty_line_then_timestamp,
    run_loop,
    TimestampLineTemplate,
    _DEFAULT_TEMPLATE,
)


class TestInferTemplate:
    def test_default_when_missing(self, tmp_path):
        t = infer_template_from_first_line(tmp_path / "nonexistent.txt")
        assert t == _DEFAULT_TEMPLATE

    def test_default_when_no_match(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("No timestamp here")
        t = infer_template_from_first_line(f)
        assert t == _DEFAULT_TEMPLATE

    def test_standard_format(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("[00:01:05.00] Speaker:\tHello")
        t = infer_template_from_first_line(f)
        assert t.open_prefix == "["
        assert "]" in t.close_prefix

    def test_padded_format(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("[ 00:01:05.00 ] Hello there")
        t = infer_template_from_first_line(f)
        assert t.open_prefix == "[ "
        assert " ] " in t.close_prefix

    def test_date_prefixed_format(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("[2026-03-23 14:30:45.00] Hello")
        t = infer_template_from_first_line(f)
        assert t.open_prefix == "["
        assert "]" in t.close_prefix


class TestBuildTimestampLine:
    def test_basic(self):
        now = datetime(2026, 3, 20, 14, 30, 45)
        line = build_timestamp_line(now, _DEFAULT_TEMPLATE)
        assert "2026-03-20 14:30:45" in line
        assert line.endswith(" ")

    def test_custom_template(self):
        tmpl = TimestampLineTemplate(open_prefix="[ ", close_prefix=" ] ")
        now = datetime(2026, 1, 1, 0, 0, 0)
        line = build_timestamp_line(now, tmpl)
        assert line.startswith("[ ")
        assert "2026-01-01 00:00:00" in line


class TestAppendTimestamp:
    def test_appends_to_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("existing content")
        line = append_empty_line_then_timestamp(f, _DEFAULT_TEMPLATE, datetime(2026, 3, 20, 10, 0, 0))
        content = f.read_text()
        assert "10:00:00" in content
        assert content.startswith("existing content\n")

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "test.txt"
        append_empty_line_then_timestamp(f, _DEFAULT_TEMPLATE, datetime(2026, 1, 1, 0, 0, 0))
        assert f.exists()


class TestRunLoop:
    def test_invalid_interval(self, tmp_path):
        with pytest.raises(ValueError, match="interval"):
            run_loop(tmp_path / "test.txt", 0)

    def test_invalid_duration(self, tmp_path):
        with pytest.raises(ValueError, match="duration"):
            run_loop(tmp_path / "test.txt", 1, run_seconds=-1)

    def test_short_run(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("")
        count = run_loop(f, interval_seconds=0.05, run_seconds=0.12)
        assert count >= 1
        assert f.read_text().count("\n") >= count


# ═══════════════════════════════════════════════════════════════════════
# daemon/debate_ai.py
# ═══════════════════════════════════════════════════════════════════════
from daemon.debate.ai_cleanup import run_debate_ai_cleanup


class TestDebateAiCleanup:
    def _sample_request(self):
        return {
            "statement": "AI will replace programmers",
            "for_args": [{"id": "1", "text": "LLMs can write code"}],
            "against_args": [{"id": "2", "text": "Humans understand context"}],
        }

    def _make_mock_response(self, text: str) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=text)]
        mock_resp.usage.input_tokens = 10
        mock_resp.usage.output_tokens = 5
        return mock_resp

    @patch("daemon.llm.adapter.anthropic.Anthropic")
    def test_successful_cleanup(self, MockClient):
        result_json = json.dumps({
            "merges": [],
            "cleaned": [{"id": "1", "text": "LLMs write code effectively"}],
            "new_arguments": [{"side": "for", "text": "AI improves productivity"}],
        })
        MockClient.return_value.messages.create.return_value = self._make_mock_response(result_json)

        result = run_debate_ai_cleanup(self._sample_request(), "key", "model")
        assert len(result["cleaned"]) == 1
        assert len(result["new_arguments"]) == 1

    @patch("daemon.llm.adapter.anthropic.Anthropic")
    def test_strips_markdown_fences(self, MockClient):
        result_json = '```json\n{"merges": [], "cleaned": [], "new_arguments": []}\n```'
        MockClient.return_value.messages.create.return_value = self._make_mock_response(result_json)

        result = run_debate_ai_cleanup(self._sample_request(), "key", "model")
        assert result == {"merges": [], "cleaned": [], "new_arguments": []}

    @patch("daemon.llm.adapter.anthropic.Anthropic")
    def test_invalid_json_raises(self, MockClient):
        MockClient.return_value.messages.create.return_value = self._make_mock_response("not json")

        with pytest.raises(json.JSONDecodeError):
            run_debate_ai_cleanup(self._sample_request(), "key", "model")


# ═══════════════════════════════════════════════════════════════════════
# daemon/rag.py
# ═══════════════════════════════════════════════════════════════════════
import daemon.rag as rag_module


class TestRagSearch:
    def setup_method(self):
        rag_module._embedder = None
        rag_module._collection = None

    @patch("daemon.rag._get_collection")
    def test_empty_collection(self, mock_get_col):
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_get_col.return_value = mock_col
        results = rag_module.search_materials("test query")
        assert len(results) == 1
        assert "No materials" in results[0]["content"]

    @patch("daemon.rag._get_embedder")
    @patch("daemon.rag._get_collection")
    def test_successful_query(self, mock_get_col, mock_get_emb):
        mock_col = MagicMock()
        mock_col.count.return_value = 3
        mock_col.query.return_value = {
            "documents": [["chunk1", "chunk2"]],
            "metadatas": [[
                {"source": "file.pdf", "page": 1, "source_type": "slides"},
                {"source": "book.pdf", "page": 5},
            ]],
        }
        mock_get_col.return_value = mock_col
        mock_emb = MagicMock()
        mock_emb.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2])
        mock_get_emb.return_value = mock_emb

        results = rag_module.search_materials("test")
        assert len(results) == 2
        assert results[0]["source_type"] == "slides"
        assert results[1]["source_type"] == "book"

    @patch("daemon.rag._get_collection")
    def test_exception_fallback(self, mock_get_col):
        mock_get_col.side_effect = Exception("ChromaDB down")
        results = rag_module.search_materials("test")
        assert "failed" in results[0]["content"].lower()


# ═══════════════════════════════════════════════════════════════════════
# daemon/summarizer.py
# ═══════════════════════════════════════════════════════════════════════
from daemon.summary.summarizer import generate_summary


class TestGenerateSummary:
    def _cfg(self, tmp_path):
        from daemon.config import Config
        return Config(
            folder=tmp_path, minutes=30, server_url="http://localhost",
            api_key="key", model="model", dry_run=False,
            host_username="h", host_password="p",
        )

    @patch("daemon.summary.summarizer.load_transcription_files")
    def test_no_files(self, mock_load, tmp_path):
        mock_load.side_effect = SystemExit(1)
        assert generate_summary(self._cfg(tmp_path), []) is None

    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[])
    def test_empty_entries(self, mock_load, tmp_path):
        assert generate_summary(self._cfg(tmp_path), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    def test_empty_text(self, mock_load, mock_extract, mock_notes, tmp_path):
        assert generate_summary(self._cfg(tmp_path), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="transcript")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_success(self, mock_create, *_mocks):
        resp_text = json.dumps([{"text": "Point 1", "source": "discussion", "time": "10:15"}])
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text=resp_text)]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp

        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None
        assert len(result["new"]) == 1
        assert result["new"][0]["time"] == "10:15"

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_fence_stripping(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text='```json\n[{"text": "P", "source": "notes"}]\n```')]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_legacy_strings(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text='["Point one", "Point two"]')]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None
        assert len(result["new"]) == 2
        assert all(p["source"] == "discussion" for p in result["new"])

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_api_error(self, mock_create, *_mocks):
        import anthropic
        mock_create.side_effect = anthropic.APIError(
            message="err", request=MagicMock(), body=None
        )
        assert generate_summary(self._cfg(MagicMock()), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_invalid_json(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text="not json")]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        assert generate_summary(self._cfg(MagicMock()), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_not_list(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text='{"not": "list"}')]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        assert generate_summary(self._cfg(MagicMock()), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_empty_response(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = []
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        assert generate_summary(self._cfg(MagicMock()), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_bad_block_type(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="image")]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        assert generate_summary(self._cfg(MagicMock()), []) is None

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.extract_all_text", return_value="text")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_invalid_source_normalized(self, mock_create, *_mocks):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text='[{"text": "P", "source": "xyz"}]')]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp
        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None
        assert result["new"][0]["source"] == "discussion"


class TestSummarizerUpdatedFormat:
    def _cfg(self, tmp_path):
        from daemon.config import Config
        return Config(
            folder=tmp_path, minutes=30, server_url="http://localhost",
            api_key="key", model="model", dry_run=False,
            host_username="h", host_password="p",
        )

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_new_points_returned(self, mock_create, *_mocks):
        resp_text = json.dumps([
            {"text": "Brand new point", "source": "discussion", "time": "15:10"},
        ])
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text=resp_text)]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp

        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None
        assert len(result["new"]) == 1
        assert result["new"][0]["text"] == "Brand new point"

    @patch("daemon.summary.summarizer.read_session_notes", return_value="")
    @patch("daemon.summary.summarizer.load_transcription_files", return_value=[(0, "t")])
    @patch("daemon.summary.summarizer.create_message")
    def test_new_only_no_updates(self, mock_create, *_mocks):
        resp_text = json.dumps([{"text": "Fresh point", "source": "notes"}])
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text=resp_text)]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp

        result = generate_summary(self._cfg(MagicMock()), [])
        assert result is not None
        assert len(result["new"]) == 1
        assert result["new"][0]["source"] == "notes"


# ═══════════════════════════════════════════════════════════════════════
# daemon/indexer.py
# ═══════════════════════════════════════════════════════════════════════
from daemon.rag.indexer import (
    chunk_text,
    _hash_file,
    _iter_supported_files,
    _load_manifest,
    _save_manifest,
    _extract_text,
    _extract_html,
    CHUNK_SIZE,
)


class TestChunkText:
    def test_short(self):
        assert chunk_text("hello", chunk_size=10, overlap=2) == ["hello"]

    def test_overlap(self):
        chunks = chunk_text("abcdefghij", chunk_size=5, overlap=2)
        assert chunks[0] == "abcde"
        assert chunks[1] == "defgh"

    def test_empty(self):
        assert chunk_text("") == []


class TestHashFile:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert _hash_file(f) == _hash_file(f)
        assert len(_hash_file(f)) == 64

    def test_different(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert _hash_file(f1) != _hash_file(f2)


class TestIterSupported:
    def test_filters(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.jpg").write_text("x")
        (tmp_path / "c.md").write_text("x")
        files = _iter_supported_files(tmp_path)
        exts = {f.suffix for f in files}
        assert ".jpg" not in exts
        assert ".txt" in exts

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.html").write_text("x")
        assert any("deep.html" in str(f) for f in _iter_supported_files(tmp_path))


class TestManifest:
    def test_roundtrip(self, tmp_path):
        files = {"a.txt": "abc", "b.pdf": "def"}
        _save_manifest(tmp_path, files)
        assert _load_manifest(tmp_path) == files

    def test_missing(self, tmp_path):
        assert _load_manifest(tmp_path) == {}

    def test_corrupt(self, tmp_path):
        (tmp_path / ".index-manifest.json").write_text("bad")
        assert _load_manifest(tmp_path) == {}


# ═══════════════════════════════════════════════════════════════════════
# training_daemon.py — session persistence functions
# ═══════════════════════════════════════════════════════════════════════
from daemon.session_state import (
    GLOBAL_STATE_FILENAME,
    load_key_points as _load_key_points,
    save_key_points as _save_key_points,
    load_daemon_state as _load_daemon_state,
    save_daemon_state as _save_daemon_state,
)


class TestSessionKeyPoints:
    def test_load_from_empty_folder(self, tmp_path):
        points, watermark = _load_key_points(tmp_path)
        assert points == []
        assert watermark == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        points = [{"text": "P1", "source": "discussion", "time": "10:15"}]
        _save_key_points(tmp_path, points, 5, None)
        loaded, wm = _load_key_points(tmp_path)
        assert loaded == points

    def test_backward_compat_loads_locked_draft(self, tmp_path):
        """Test migration from old summary_cache.json format."""
        cache = tmp_path / "key_points.json"
        cache.write_text('{"locked": [{"text": "L1"}], "draft": [{"text": "D1"}]}')
        loaded, _ = _load_key_points(tmp_path)
        assert len(loaded) == 2

    def test_load_daemon_state(self, tmp_path):
        state_file = tmp_path / GLOBAL_STATE_FILENAME
        # Old stack format — should be migrated to {main, talk}
        state_file.write_text('{"stack": [{"name": "Test", "started_at": "2026-03-23T09:00:00", "ended_at": null, "summary_watermark": 0}]}')
        state = _load_daemon_state(tmp_path)
        assert state["main"]["name"] == "Test"
        assert state["talk"] is None

    def test_load_daemon_state_missing(self, tmp_path):
        state = _load_daemon_state(tmp_path)
        assert state == {"main": None, "talk": None}

    def test_save_daemon_state_roundtrip(self, tmp_path):
        daemon_state = {
            "main": {"name": "W", "started_at": "2026-03-23T09:00:00", "status": "active", "summary_watermark": 42},
            "talk": None,
        }
        _save_daemon_state(tmp_path, daemon_state)
        loaded = _load_daemon_state(tmp_path)
        assert loaded == daemon_state


class TestExtractors:
    def test_text(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello")
        assert _extract_text(f) == [(1, "Hello")]

    def test_empty_text(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert _extract_text(f) == []

    def test_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text("<p>Hello</p><b>World</b>")
        pages = _extract_html(f)
        assert "Hello" in pages[0][1]
        assert "<p>" not in pages[0][1]
