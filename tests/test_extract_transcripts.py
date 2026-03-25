from datetime import datetime

from extract_transcripts import extract_entries, format_entry, format_summary_line


def test_extract_entries_filters_iso_datetime_range(tmp_path):
    transcript = tmp_path / "20260325 1000 session.txt"
    transcript.write_text(
        "[2026-03-25 09:59:00.00] [victor] before\n"
        "[2026-03-25 10:05:00.00] [victor] trainer line\n"
        "[2026-03-25 10:06:00.00] \n"
        "[2026-03-25 18:00:00.00] [victor] boundary\n"
        "[2026-03-25 18:00:01.00] [victor] after\n"
    )

    start = datetime.fromisoformat("2026-03-25T10:00")
    end = datetime.fromisoformat("2026-03-25T18:00")

    entries = extract_entries(tmp_path, start, end)

    assert [format_entry(dt, text) for dt, text in entries] == [
        "2026-03-25T10:05 [victor] trainer line",
        "2026-03-25T18:00 [victor] boundary",
    ]


def test_extract_entries_time_only_uses_existing_elapsed_conversion(tmp_path):
    transcript = tmp_path / "20260325 1000 elapsed.txt"
    transcript.write_text("[00:01:00.00] [victor] hello\n")

    start = datetime.fromisoformat("2026-03-25T10:00")
    end = datetime.fromisoformat("2026-03-25T10:02")

    entries = extract_entries(tmp_path, start, end)

    assert len(entries) == 1
    assert entries[0][0] == datetime(2026, 3, 25, 10, 1)
    assert entries[0][1] == "[victor] hello"


def test_extract_entries_does_not_skip_old_filename_with_new_timestamps(tmp_path):
    transcript = tmp_path / "20260322 2100 Transcription.txt"
    transcript.write_text(
        "[2026-03-25 10:05:00.00] [victor] today line\n"
        "[2026-03-22 10:05:00.00] [victor] old line\n"
    )

    start = datetime.fromisoformat("2026-03-25T10:00")
    end = datetime.fromisoformat("2026-03-25T10:10")

    entries = extract_entries(tmp_path, start, end)

    assert [format_entry(dt, text) for dt, text in entries] == [
        "2026-03-25T10:05 [victor] today line",
    ]


def test_summary_line_multiple_speakers():
    start = datetime.fromisoformat("2026-03-25T10:00")
    end = datetime.fromisoformat("2026-03-25T18:00")
    entries = [
        (datetime.fromisoformat("2026-03-25T10:05"), "[victor] one"),
        (datetime.fromisoformat("2026-03-25T10:06"), "[victor] two"),
        (datetime.fromisoformat("2026-03-25T10:07"), "[audience] question"),
    ]

    summary = format_summary_line(entries, start, end)

    assert summary == "[victor] 2 lines, [audience] 1 line over 8h"


def test_summary_line_single_speaker_duration_with_minutes():
    start = datetime.fromisoformat("2026-03-25T10:00")
    end = datetime.fromisoformat("2026-03-25T15:30")
    entries = [
        (datetime.fromisoformat("2026-03-25T10:05"), "[victor] one"),
        (datetime.fromisoformat("2026-03-25T10:06"), "[victor] two"),
    ]

    summary = format_summary_line(entries, start, end)

    assert summary == "[victor] 2 lines over 5h 30m"
