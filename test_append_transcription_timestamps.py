from datetime import datetime
from pathlib import Path

import pytest

from scripts.append_transcription_timestamps import build_marker_line, run_loop


def test_build_marker_line_matches_parser_shape():
    line = build_marker_line(
        datetime(2026, 3, 19, 7, 48, 30),
        speaker="Timestamp",
        label="[auto-marker]",
    )

    assert line.startswith("[07:48:30.00] Timestamp:\t")
    assert "[auto-marker] 2026-03-19 07:48:30" in line


def test_run_loop_appends_expected_count(tmp_path: Path):
    transcript_file = tmp_path / "transcription.txt"
    transcript_file.write_text("[07:48:00.00] Speaker:\tHello", encoding="utf-8")

    appended = run_loop(
        file_path=transcript_file,
        interval_seconds=0.01,
        speaker="Timestamp",
        label="[auto-marker]",
        ticks=2,
    )

    assert appended == 2

    lines = transcript_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[1].startswith("[")
    assert "] Timestamp:\t[auto-marker] " in lines[1]
    assert lines[2].startswith("[")


def test_run_loop_rejects_non_positive_interval(tmp_path: Path):
    with pytest.raises(ValueError):
        run_loop(
            file_path=tmp_path / "transcription.txt",
            interval_seconds=0,
            speaker="Timestamp",
            label="[auto-marker]",
            ticks=1,
        )

