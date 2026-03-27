import json
from datetime import datetime

from daemon.transcript_normalizer import (
    default_offset_file_for,
    normalize_folder_incremental,
    normalize_incremental,
)


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_case1_raw_file_without_offset(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 00:00:00.03 ] Victor:\tHello\n", encoding="utf-8")

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 10))

    assert result.written_lines == 1
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[10:10] Victor: Hello",
    ]


def test_case2_offset_exists_same_speaker_continues(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 00:00:00.03 ] Victor:\tFirst\n", encoding="utf-8")

    normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 0))

    with raw.open("a", encoding="utf-8") as f:
        f.write("second without speaker\n")

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 5))

    assert result.written_lines == 1
    assert _lines(tmp_path / "2026-03-25 transcription.txt")[-1] == "[10:05] Victor: second without speaker"


def test_case3_offset_exists_new_participant_switches_speaker(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 00:00:00.03 ] Victor:\tIntro\n", encoding="utf-8")

    normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 0))

    with raw.open("a", encoding="utf-8") as f:
        f.write("[12:58:36.05] Audience:\tQuestion\n")
        f.write("follow up\n")

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 6))

    assert result.written_lines == 2
    assert _lines(tmp_path / "2026-03-25 transcription.txt")[-2:] == [
        "[10:06] Audience: Question",
        "[10:06] Audience: follow up",
    ]


def test_case4_old_file_has_offset_but_newer_file_takes_over_with_own_offset(tmp_path):
    old_raw = tmp_path / "20260324 0900 Transcription.txt"
    old_raw.write_text("[ 00:00:00.03 ] Victor:\tOld start\n", encoding="utf-8")
    normalize_incremental(old_raw, now=datetime(2026, 3, 24, 9, 10))

    with old_raw.open("a", encoding="utf-8") as f:
        f.write("old tail\n")

    new_raw = tmp_path / "20260325 0900 Transcription.txt"
    new_raw.write_text("[ 00:00:00.03 ] Audience:\tNew day start\n", encoding="utf-8")

    results = normalize_folder_incremental(tmp_path, now=datetime(2026, 3, 25, 10, 20))

    assert len(results) == 2
    assert _lines(tmp_path / "2026-03-24 transcription.txt")[-1] == "[10:20] Victor: old tail"
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == ["[10:20] Audience: New day start"]

    new_offset = default_offset_file_for(new_raw)
    assert new_offset.exists()
    data = json.loads(new_offset.read_text(encoding="utf-8"))
    assert data["files"][new_raw.name]["offset"] > 0


def test_case5_offset_exists_but_no_new_non_empty_transcription(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text("[ 00:00:00.03 ] Victor:\tHello\n", encoding="utf-8")
    normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 0))

    with raw.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.write("[ 2026-03-25 10:01:00.00 ]\n")

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 1))

    assert result.written_lines == 0


def test_case6_no_offset_alternating_speakers_a_b_a(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 00:00:00.03 ] Victor:\tone\n"
        "[12:58:36.05] Audience:\ttwo\n"
        "[ 00:00:02.00 ] Victor:\tthree\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 12))

    assert result.written_lines == 3
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[10:12] Victor: one",
        "[10:12] Audience: two",
        "[10:12] Victor: three",
    ]


def test_case7_all_normalized_lines_use_poll_timestamp(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 2026-03-25 17:41:49.00 ] Victor:\tFirst\n"
        "[12:58:36.05] Audience:\tSecond\n",
        encoding="utf-8",
    )

    normalize_incremental(raw, now=datetime(2026, 3, 25, 20, 45))

    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[20:45] Victor: First",
        "[20:45] Audience: Second",
    ]


def test_case8_yesterday_offset_then_today_new_file_writes_both_days(tmp_path):
    yday_raw = tmp_path / "20260324 2100 Transcription.txt"
    yday_raw.write_text("[ 00:00:00.03 ] Victor:\tYesterday first\n", encoding="utf-8")
    normalize_incremental(yday_raw, now=datetime(2026, 3, 24, 21, 10))

    with yday_raw.open("a", encoding="utf-8") as f:
        f.write("yesterday continuation\n")

    today_raw = tmp_path / "20260325 0900 Transcription.txt"
    today_raw.write_text("[ 00:00:00.03 ] Audience:\tToday first\n", encoding="utf-8")

    normalize_folder_incremental(tmp_path, now=datetime(2026, 3, 25, 9, 30))

    assert _lines(tmp_path / "2026-03-24 transcription.txt")[-1] == "[09:30] Victor: yesterday continuation"
    assert _lines(tmp_path / "2026-03-25 transcription.txt")[0] == "[09:30] Audience: Today first"


def test_case9_real_identified_segment_speaker_propagation(tmp_path):
    raw = tmp_path / "20260322 2100 Transcription.txt"
    raw.write_text(
        "[60:53:42.42] Audience:\tOrchestration, agents, but I also have a question here.\n"
        "[ 2026-03-25 17:41:53.00 ]\n"
        "[ 2026-03-25 17:41:57.00 ]\n"
        "[ 2026-03-25 17:42:02.00 ]\n"
        "[ 2026-03-25 17:42:11.00 ]  I don't know enough information, or is it correct?\n"
        "[ 60:54:07.34 ] Victor:\tYou said it, I wanted to say it.\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 20, 1))

    assert result.written_lines == 3
    assert _lines(tmp_path / "2026-03-22 transcription.txt") == [
        "[20:01] Audience: Orchestration, agents, but I also have a question here.",
    ]
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[20:01] Audience: I don't know enough information, or is it correct?",
        "[20:01] Victor: You said it, I wanted to say it.",
    ]


def test_case10_single_raw_with_absolute_dates_writes_yesterday_and_today(tmp_path):
    raw = tmp_path / "20260322 2100 Transcription.txt"
    raw.write_text(
        "[ 2026-03-24 09:30:00.00 ] Victor:\tYesterday line\n"
        "[ 2026-03-25 10:00:00.00 ] Audience:\tToday line\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 20, 15))

    assert result.written_lines == 2
    assert _lines(tmp_path / "2026-03-24 transcription.txt") == [
        "[20:15] Victor: Yesterday line",
    ]
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[20:15] Audience: Today line",
    ]


def test_case11_filters_suspicious_low_signal_lines(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 2026-03-25 10:00:00.00 ] Victor:\t(upbeat music)\n"
        "[ 2026-03-25 10:00:01.00 ] Victor:\tMUSIC\n"
        "[ 2026-03-25 10:00:02.00 ] Victor:\tRussian inaudible.\n"
        "[ 2026-03-25 10:00:03.00 ] Victor:\tHoming\n"
        "[ 2026-03-25 10:00:04.00 ] Victor:\tReal sentence that should stay.\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 30))

    assert result.written_lines == 1
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[10:30] Victor: Real sentence that should stay.",
    ]


def test_case12_keeps_contentful_line_even_if_contains_noise_word(tmp_path):
    raw = tmp_path / "20260325 1000 Transcription.txt"
    raw.write_text(
        "[ 2026-03-25 10:00:00.00 ] Victor:\tSilence I have a feature request for host UI.\n",
        encoding="utf-8",
    )

    result = normalize_incremental(raw, now=datetime(2026, 3, 25, 10, 40))

    assert result.written_lines == 1
    assert _lines(tmp_path / "2026-03-25 transcription.txt") == [
        "[10:40] Victor: Silence I have a feature request for host UI.",
    ]


