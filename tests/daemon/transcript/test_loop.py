from pathlib import Path
from unittest.mock import patch

from daemon.transcript.loop import TranscriptNormalizerRunner, _LLM_FILTER_STATS
from daemon.transcript.normalizer import NormalizeResult


def test_normalizer_log_preview_strips_leading_transcript_timestamp(tmp_path):
    def _fake_normalize_folder_incremental(_folder, line_pre_filter=None):
        _LLM_FILTER_STATS["last_ms"] = 2622
        _LLM_FILTER_STATS["provider"] = "OLLAMA"
        return [
            NormalizeResult(
                raw_file=Path("20260329 1500 Transcription.txt"),
                offset_file=tmp_path / "normalization.offset.txt",
                read_bytes=10,
                written_lines=1,
                output_files=[tmp_path / "2026-03-29 transcription.txt"],
                reset_offset=False,
                raw_words=81,
                written_words=22,
                first_words="[ 14:52:12 ] Tocmai atunci cand oamenii adorm la webinar",
            )
        ]

    runner = TranscriptNormalizerRunner(tmp_path, interval_seconds=1, enabled=True)
    runner._next_run_at = 0

    with patch("daemon.transcript.loop.normalize_folder_incremental", side_effect=_fake_normalize_folder_incremental):
        with patch("daemon.transcript.loop.log.info") as info_mock:
            runner.tick()

    message = info_mock.call_args.args[1]
    assert message == (
        "Transcripted 22 words (of 81 🤖 2622ms OLLAMA): "
        "Tocmai atunci cand oamenii adorm la webinar ..."
    )
    assert "\n" not in message
    assert "[ 14:52:12 ]" not in message
