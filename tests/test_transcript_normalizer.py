from daemon.transcript_normalizer import (
    normalize_incremental,
    normalize_latest_in_folder,
)


def test_normalize_incremental_uses_last_valid_clock_and_tracks_speaker(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 2026-03-25 17:41:49.00 ] Victor:\tFirst line\n"
        "[60:54:07.34] Audience:\tQuestion\n"
        "[ 2026-03-25 17:42:11.00 ]\n"
        "Follow-up without speaker\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw)

    assert result.written_lines == 3
    out = tmp_path / "2026-03-25 transcription.txt"
    assert out.exists()
    assert out.read_text(encoding="utf-8").splitlines() == [
        "[17:41] Victor: First line",
        "[17:41] Audience: Question",
        "[17:42] Audience: Follow-up without speaker",
    ]


def test_normalize_incremental_handles_partial_last_line_across_runs(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 2026-03-25 10:00:00.00 ] Victor:\tHello par", encoding="utf-8")

    first = normalize_incremental(raw)
    assert first.written_lines == 0

    with raw.open("a", encoding="utf-8") as f:
        f.write("tial\n")
        f.write("continuation line\n")

    second = normalize_incremental(raw)
    assert second.written_lines == 2

    out = tmp_path / "2026-03-25 transcription.txt"
    assert out.read_text(encoding="utf-8").splitlines() == [
        "[10:00] Victor: Hello partial",
        "[10:00] Victor: continuation line",
    ]


def test_normalize_incremental_resets_offset_when_raw_file_is_truncated(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 2026-03-25 10:00:00.00 ] Victor:\tFirst line is intentionally much longer to force truncation detection\n",
        encoding="utf-8",
    )

    first = normalize_incremental(raw)
    assert first.reset_offset is False

    # Simulate restart/rotation by replacing with a smaller file.
    raw.write_text("[ 2026-03-26 09:00:00.00 ] Audience:\tFresh start\n", encoding="utf-8")

    second = normalize_incremental(raw)
    assert second.reset_offset is True
    out = tmp_path / "2026-03-26 transcription.txt"
    assert out.read_text(encoding="utf-8").splitlines() == [
        "[09:00] Audience: Fresh start",
    ]


def test_normalize_latest_in_folder_ignores_normalized_output_files(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 2026-03-25 10:00:00.00 ] Victor:\tRaw\n", encoding="utf-8")

    # This should never be treated as raw input.
    (tmp_path / "2026-03-25 transcription.txt").write_text(
        "[10:00] Victor: already normalized\n",
        encoding="utf-8",
    )

    result = normalize_latest_in_folder(tmp_path)

    assert result is not None
    assert result.raw_file == raw
    assert result.written_lines == 1
