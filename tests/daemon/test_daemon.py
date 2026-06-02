"""Unit tests for daemon/ modules — indexer, debate_ai, rag, session_state."""
import json
from unittest.mock import MagicMock, patch

import anthropic
import pytest

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
        # ai_cleanup reads block.text only for real anthropic TextBlock instances.
        mock_resp.content = [anthropic.types.TextBlock(type="text", text=text)]
        return mock_resp

    @patch("daemon.debate.ai_cleanup.create_message")
    def test_successful_cleanup(self, mock_create):
        result_json = json.dumps({
            "merges": [],
            "cleaned": [{"id": "1", "text": "LLMs write code effectively"}],
            "new_arguments": [{"side": "for", "text": "AI improves productivity"}],
        })
        mock_create.return_value = self._make_mock_response(result_json)

        result = run_debate_ai_cleanup(self._sample_request(), "key", "model")
        assert len(result["cleaned"]) == 1
        assert len(result["new_arguments"]) == 1

    @patch("daemon.debate.ai_cleanup.create_message")
    def test_strips_markdown_fences(self, mock_create):
        result_json = '```json\n{"merges": [], "cleaned": [], "new_arguments": []}\n```'
        mock_create.return_value = self._make_mock_response(result_json)

        result = run_debate_ai_cleanup(self._sample_request(), "key", "model")
        assert result == {"merges": [], "cleaned": [], "new_arguments": []}

    @patch("daemon.debate.ai_cleanup.create_message")
    def test_invalid_json_raises(self, mock_create):
        mock_create.return_value = self._make_mock_response("not json")

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
# daemon/indexer.py
# ═══════════════════════════════════════════════════════════════════════
from daemon.rag.indexer import (
    _extract_html,
    _extract_text,
    _hash_file,
    _iter_supported_files,
    _load_manifest,
    _save_manifest,
    chunk_text,
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
    load_daemon_state as _load_daemon_state,
    save_daemon_state as _save_daemon_state,
)


class TestDaemonState:
    def test_load_new_format(self, tmp_path):
        state_file = tmp_path / GLOBAL_STATE_FILENAME
        state_file.write_text('{"active_session_id": "abc123"}')
        state = _load_daemon_state(tmp_path)
        assert state["active_session_id"] == "abc123"

    def test_load_legacy_format_returned_as_is(self, tmp_path):
        # Old formats (stack / main-talk) are returned raw for the caller to migrate.
        state_file = tmp_path / GLOBAL_STATE_FILENAME
        state_file.write_text('{"stack": [{"name": "Test"}]}')
        assert _load_daemon_state(tmp_path) == {"stack": [{"name": "Test"}]}

    def test_load_daemon_state_missing(self, tmp_path):
        assert _load_daemon_state(tmp_path) == {}

    def test_save_daemon_state_roundtrip(self, tmp_path):
        daemon_state = {"active_session_id": "session-42"}
        _save_daemon_state(tmp_path, daemon_state)
        assert _load_daemon_state(tmp_path) == daemon_state


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
