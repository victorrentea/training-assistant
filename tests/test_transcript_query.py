from datetime import datetime

from daemon.transcript_query import QueryRange, query_lines, _resolve_query_range


class _Args:
    def __init__(
        self,
        today=False,
        yesterday_afternoon=False,
        last_minutes=None,
        from_dt=None,
        to_dt=None,
        iso_range=None,
    ):
        self.today = today
        self.yesterday_afternoon = yesterday_afternoon
        self.last_minutes = last_minutes
        self.from_dt = from_dt
        self.to_dt = to_dt
        self.iso_range = iso_range or []


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


def test_resolve_today():
    now = datetime(2026, 3, 26, 10, 15)
    q = _resolve_query_range(_Args(today=True), now)
    assert q.start == datetime(2026, 3, 26, 0, 0)
    assert q.end == now


def test_resolve_last_minutes():
    now = datetime(2026, 3, 26, 10, 15)
    q = _resolve_query_range(_Args(last_minutes=10), now)
    assert q.start == datetime(2026, 3, 26, 10, 5)
    assert q.end == now


def test_resolve_positional_iso_range():
    now = datetime(2026, 3, 26, 10, 15)
    q = _resolve_query_range(
        _Args(iso_range=["2026-03-25T17:00:00", "2026-03-26T08:23:12"]),
        now,
    )
    assert q.start == datetime(2026, 3, 25, 17, 0, 0)
    assert q.end == datetime(2026, 3, 26, 8, 23, 12)
