from datetime import datetime

from daemon.transcript_query import QueryRange, query_lines, _resolve_query_range


class _Args:
    def __init__(self, from_iso, to_iso):
        self.from_iso = from_iso
        self.to_iso = to_iso


def test_query_lines_from_two_days(tmp_path):
    (tmp_path / "2026-03-25 transcription.txt").write_text(
        "[11:59] V: before\n"
        "[12:00] V: start\n"
        "[18:30] A: q1\n",
        encoding="utf-8",
    )
    (tmp_path / "2026-03-26 transcription.txt").write_text(
        "[08:00] V: day2\n"
        "[09:10] A: end\n",
        encoding="utf-8",
    )

    q = QueryRange(
        start=datetime(2026, 3, 25, 12, 0),
        end=datetime(2026, 3, 26, 9, 0),
    )

    lines = query_lines(tmp_path, q)
    assert lines == [
        "[2026-03-25 12:00] V: start",
        "[2026-03-25 18:30] A: q1",
        "[2026-03-26 08:00] V: day2",
    ]


def test_resolve_positional_iso_range():
    q = _resolve_query_range(_Args("2026-03-25T17:00:00", "2026-03-26T08:23:12"))
    assert q.start == datetime(2026, 3, 25, 17, 0, 0)
    assert q.end == datetime(2026, 3, 26, 8, 23, 12)


def test_rejects_non_iso_space_format():
    try:
        _resolve_query_range(_Args("2026-03-25 17:00:00", "2026-03-26T08:23:12"))
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "ISO format" in str(exc)
