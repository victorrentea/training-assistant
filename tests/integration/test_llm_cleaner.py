"""
Integration tests for daemon/transcript/llm_cleaner.py.

Requires Ollama running locally with gemma3:4b pulled:
    brew services start ollama
    ollama pull gemma3:4b

Tests call the real Ollama API — they are slow (~1-2s per line).
Skipped automatically if Ollama is not reachable.
"""
import json
import urllib.request
import urllib.error
import tempfile
from pathlib import Path

import pytest

from daemon.transcript.llm_cleaner import (
    call_ollama, clean_line, clean_file,
    is_content_line, is_deterministic_garbage,
    OLLAMA_URL, MODEL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL.rsplit('/api', 1)[0]}/api/tags", timeout=2) as r:
            tags = json.loads(r.read())
            return any(m["name"].startswith(MODEL.split(":")[0]) for m in tags.get("models", []))
    except Exception:
        return False


requires_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running or gemma3:4b not pulled"
)


# ---------------------------------------------------------------------------
# Unit-level (no Ollama needed)
# ---------------------------------------------------------------------------

class TestIsContentLine:
    def test_empty_string(self):
        assert not is_content_line("")

    def test_whitespace_only(self):
        assert not is_content_line("   \n")

    def test_timestamp_only_absolute(self):
        assert not is_content_line("[ 2026-03-26 14:21:04.00 ] \n")

    def test_timestamp_only_relative(self):
        assert not is_content_line("[ 00:01:23.00 ]\n")

    def test_line_with_content(self):
        assert is_content_line("[ 2026-03-26 14:27:05.00 ]  Reține că am railway instalat, CLI.\n")

    def test_line_with_speaker(self):
        assert is_content_line("[00:00:11.53] Victor:\tVreau să găsești fișierul.\n")


# ---------------------------------------------------------------------------
# Deterministic pre-filter tests (no Ollama needed)
# ---------------------------------------------------------------------------

class TestDeterministicGarbage:
    """is_deterministic_garbage() catches obvious patterns without LLM."""

    def test_chinese_characters(self):
        assert is_deterministic_garbage("1/2 茶 (4g)  1/2 茶 (4g)")

    def test_japanese_text(self):
        assert is_deterministic_garbage("真を見るためにスマートフォンを使用して字幕を作成する必要があります。")

    def test_cyrillic_text(self):
        assert is_deterministic_garbage("Подписывайтесь на мой канал, ставьте лайки.")

    def test_recipe_tsp(self):
        assert is_deterministic_garbage("1/2 tsp Vanilla extract 1/2 tsp Salt 1/2 tsp Cinnamon")

    def test_recipe_cup(self):
        assert is_deterministic_garbage("3/4 cup flour 1/4 cup sugar")

    def test_single_word_repeated_5x(self):
        assert is_deterministic_garbage("Război, război, război, război, război, război, război,")

    def test_single_word_repeated_exactly_4x_not_flagged(self):
        # 4 repetitions is borderline — let the LLM decide
        assert not is_deterministic_garbage("test, test, test, test")

    def test_real_romanian_not_flagged(self):
        assert not is_deterministic_garbage("Reține că am railway instalat, CLI.")

    def test_real_english_not_flagged(self):
        assert not is_deterministic_garbage("I want you to find the file and open it.")


# ---------------------------------------------------------------------------
# LLM integration tests — garbage detection (LLM-only cases)
# ---------------------------------------------------------------------------

class TestGarbageDetection:
    """Each test sends one garbage line via clean_line(); expects [SKIP]."""

    @requires_ollama
    def test_skip_youtube_boilerplate(self):
        line = "[ 2026-03-26 14:37:34.00 ]  Thanks for watching and don't forget to like and subscribe!"
        assert clean_line(line) == "[SKIP]"

    @requires_ollama
    def test_skip_single_word_repeated(self):
        # Caught by deterministic filter
        line = "[ 2026-03-26 14:35:46.00 ]  Război, război, război, război, război, război, război, război,"
        assert clean_line(line) == "[SKIP]"

    @requires_ollama
    def test_skip_chinese_characters(self):
        # Caught by deterministic filter
        line = "[ 2026-03-26 14:37:58.00 ]  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g)"
        assert clean_line(line) == "[SKIP]"

    @requires_ollama
    def test_skip_japanese_text(self):
        # Caught by deterministic filter
        line = "[ 2026-03-26 14:40:15.00 ]  真を見るためにスマートフォンを使用して字幕を作成する必要があります。"
        assert clean_line(line) == "[SKIP]"

    @requires_ollama
    def test_skip_recipe_ingredients(self):
        # Caught by deterministic filter
        line = "[ 2026-03-26 14:38:40.00 ]  1/2 tsp (2g) Vanilla extract 1/2 tsp (2g) Salt 1/2 tsp (2g) Cinnamon powder"
        assert clean_line(line) == "[SKIP]"

    @requires_ollama
    def test_skip_hardware_tutorial_with_subscribe(self):
        # LLM catches this — "subscribe" is a strong signal
        line = "[ 2026-03-26 14:37:34.00 ]  Disconnect the power cord from the main board. Thanks for watching and don't forget to like and subscribe!"
        assert clean_line(line) == "[SKIP]"


# ---------------------------------------------------------------------------
# LLM integration tests — real content preservation
# ---------------------------------------------------------------------------

class TestRealContentPreserved:
    """Each test sends a real trainer line; expects it NOT to be [SKIP]."""

    @requires_ollama
    def test_keep_romanian_instruction(self):
        line = "[ 2026-03-26 14:27:05.00 ]  Reține că am railway instalat, CLI."
        result = clean_line(line)
        assert result != "[SKIP]"
        assert "railway" in result  # technical term must survive

    @requires_ollama
    def test_keep_romanian_dev_sentence(self):
        line = "[ 2026-03-26 14:38:22.00 ]  Vreau sa va arat ca ori de cate ori vrei sa faci o schimbare in daemon, trebuie sa faci push pe master."
        result = clean_line(line)
        assert result != "[SKIP]"
        assert "daemon" in result
        assert "master" in result

    @requires_ollama
    def test_keep_english_technical_question(self):
        line = "[ 2026-03-26 14:39:22.00 ]  Ce înseamnă 'Speaker Deactivation' și 'Voice Activity Detection'?"
        result = clean_line(line)
        assert result != "[SKIP]"
        assert "Speaker Deactivation" in result

    @requires_ollama
    def test_keep_mixed_language_sentence(self):
        line = "[ 2026-03-26 14:32:42.00 ]  Conversiunea de transcripție pentru execuție locală pe Mac OS"
        result = clean_line(line)
        assert result != "[SKIP]"

    @requires_ollama
    def test_deduplicates_repeated_real_sentence(self):
        line = "[ 2026-03-26 14:30:50.00 ]  If you have any questions please ask. If you have any questions please ask. If you have any questions please ask."
        result = clean_line(line)
        assert result != "[SKIP]"
        # Should appear only once in output
        assert result.count("If you have any questions") == 1


# ---------------------------------------------------------------------------
# File-level integration test
# ---------------------------------------------------------------------------

class TestCleanFile:

    @requires_ollama
    def test_clean_file_skips_garbage_and_keeps_real(self, tmp_path):
        raw_content = """\
[ 2026-03-26 14:20:52.00 ]
[ 2026-03-26 14:21:04.00 ]
[ 2026-03-26 14:27:05.00 ]  Reține că am railway instalat, CLI.
[ 2026-03-26 14:27:28.00 ]  Select the path you want to run. Follow me: http://bit.ly/ISCVideo New HD video every 2 Days,
[ 2026-03-26 14:28:05.00 ]
[ 2026-03-26 14:28:36.00 ]  Comentează, nu șterge codul. Acum începeți discuția.
[ 2026-03-26 14:35:46.00 ]  Război, război, război, război, război, război, război, război,
[ 2026-03-26 14:36:27.00 ]  Ideea este, mi-ar trebui să-i pot da două surse de input la care să asculte.
[ 2026-03-26 14:37:34.00 ]  Disconnect the power cord. Thanks for watching and don't forget to like and subscribe!
[ 2026-03-26 14:37:58.00 ]  1/2 茶 (4g)  1/2 茶 (4g)  1/2 茶 (4g)
"""
        input_file = tmp_path / "raw.txt"
        output_file = tmp_path / "cleaned.txt"
        input_file.write_text(raw_content, encoding="utf-8")

        stats = clean_file(input_file, output_file, progress=False)

        assert output_file.exists()
        output = output_file.read_text(encoding="utf-8")

        # Real lines must survive
        assert "railway" in output
        assert "Comentează" in output
        assert "două surse de input" in output

        # Garbage must be gone
        assert "subscribe" not in output
        assert "Război, război, război" not in output
        assert "茶" not in output

        # Stats sanity
        assert stats["content"] == 7  # 7 non-empty content lines
        assert stats["skipped"] >= 3  # at least the 3 obvious ones
        assert stats["kept"] >= 3
        assert stats["errors"] == 0

    @requires_ollama
    def test_clean_file_passthrough_empty_lines(self, tmp_path):
        """Timestamp-only lines are passed through without calling LLM."""
        raw_content = (
            "[ 2026-03-26 14:20:52.00 ] \n"
            "[ 2026-03-26 14:21:04.00 ] \n"
            "[ 2026-03-26 14:21:07.00 ] \n"
        )
        input_file = tmp_path / "raw.txt"
        output_file = tmp_path / "cleaned.txt"
        input_file.write_text(raw_content, encoding="utf-8")

        stats = clean_file(input_file, output_file, progress=False)

        assert stats["content"] == 0
        assert stats["kept"] == 0
        assert stats["skipped"] == 0
        # Output identical to input (timestamps preserved)
        assert output_file.read_text() == raw_content
