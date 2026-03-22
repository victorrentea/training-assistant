from datetime import datetime
from pathlib import Path

import pytest

from daemon.transcript_timestamps import (
    append_empty_line_then_timestamp,
    build_timestamp_line,
    infer_template_from_first_line,
    run_loop,
)


def test_infer_template_from_first_line_preserves_shape(tmp_path: Path):
    transcript_file = tmp_path / "transcription.txt"
    transcript_file.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    template = infer_template_from_first_line(transcript_file)
    line = build_timestamp_line(datetime(2026, 3, 19, 14, 50, 1), template)

    assert line == "[ 14:50:01.00 ] "


def test_append_empty_line_then_timestamp(tmp_path: Path):
    transcript_file = tmp_path / "transcription.txt"
    transcript_file.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    template = infer_template_from_first_line(transcript_file)
    append_empty_line_then_timestamp(
        transcript_file,
        template,
        now=datetime(2026, 3, 19, 14, 50, 1),
    )

    assert (
        transcript_file.read_text(encoding="utf-8")
        == "[ 00:00:22.50 ] Victor:\tHello\n[ 14:50:01.00 ] "
    )


def test_run_loop_appends_expected_count(tmp_path: Path):
    transcript_file = tmp_path / "transcription.txt"
    transcript_file.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    appended = run_loop(
        file_path=transcript_file,
        interval_seconds=0.01,
        run_seconds=0.025,
    )

    assert appended >= 2

    text = transcript_file.read_text(encoding="utf-8")
    assert text.count(".00 ] ") == appended
    assert text.count("\n[") >= 1


def test_run_loop_rejects_non_positive_interval(tmp_path: Path):
    with pytest.raises(ValueError):
        run_loop(
            file_path=tmp_path / "transcription.txt",
            interval_seconds=0,
            run_seconds=1,
        )


def test_run_loop_rejects_non_positive_run_seconds(tmp_path: Path):
    with pytest.raises(ValueError):
        run_loop(
            file_path=tmp_path / "transcription.txt",
            interval_seconds=0.01,
            run_seconds=0,
        )


def test_run_loop_keeps_console_output_compact(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    transcript_file = tmp_path / "transcription.txt"
    transcript_file.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    run_loop(
        file_path=transcript_file,
        interval_seconds=0.01,
        run_seconds=0.025,
    )

    output = capsys.readouterr().out
    assert "[info] Appending lines to:" in output
    assert "[info] Stopped after" in output
    assert "appended timestamp prefix" not in output


