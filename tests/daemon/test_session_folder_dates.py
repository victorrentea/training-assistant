"""Date prefixes of session folder names: '2026-09-4+9 X', '2026-08-31..1 X', ..."""
from datetime import date

import pytest

from daemon.config import find_session_folder, parse_session_folder_dates


@pytest.mark.parametrize(
    "name, ranges",
    [
        ("2026-09-15 AI@Acme", [(date(2026, 9, 15), date(2026, 9, 15))]),
        ("2026-09-14..15 AI@Konecranes", [(date(2026, 9, 14), date(2026, 9, 15))]),
        ("2026-09-4+9 AI@Nice", [(date(2026, 9, 4), date(2026, 9, 4)), (date(2026, 9, 9), date(2026, 9, 9))]),
        ("2026-08-31..1 AI@Adobe", [(date(2026, 8, 31), date(2026, 9, 1))]),
        ("2026-09-4 Single digit", [(date(2026, 9, 4), date(2026, 9, 4))]),
        ("2026-08-31..09-01 MM-DD end", [(date(2026, 8, 31), date(2026, 9, 1))]),
        ("2026-12-31..2027-01-02 Full end", [(date(2026, 12, 31), date(2027, 1, 2))]),
        ("2026-12-30+2 Year rollover", [(date(2026, 12, 30), date(2026, 12, 30)), (date(2027, 1, 2), date(2027, 1, 2))]),
        ("2026-10-12+14..16 EDA@Amex", [(date(2026, 10, 12), date(2026, 10, 12)), (date(2026, 10, 14), date(2026, 10, 16))]),
        ("2026-10-12..13+15 X", [(date(2026, 10, 12), date(2026, 10, 13)), (date(2026, 10, 15), date(2026, 10, 15))]),
        ("2026-09-15", [(date(2026, 9, 15), date(2026, 9, 15))]),
        ("2026-09-15_underscore", [(date(2026, 9, 15), date(2026, 9, 15))]),
    ],
)
def test_parse(name, ranges):
    assert list(parse_session_folder_dates(name).ranges) == ranges


def test_no_date_prefix():
    assert parse_session_folder_dates("Random notes") is None


def test_end_before_start_rejected():
    with pytest.raises(ValueError):
        parse_session_folder_dates("2026-09-15..2026-09-10 Backwards")


def test_covers_range_vs_two_days():
    rng = parse_session_folder_dates("2026-08-31..2 X")
    assert rng.covers(date(2026, 9, 1)) and rng.covers(date(2026, 9, 2))
    two = parse_session_folder_dates("2026-09-4+9 X")
    assert two.covers(date(2026, 9, 4)) and two.covers(date(2026, 9, 9))
    assert not two.covers(date(2026, 9, 5))
    mixed = parse_session_folder_dates("2026-10-12+14..16 X")
    assert [mixed.covers(date(2026, 10, d)) for d in range(11, 18)] == [False, True, False, True, True, True, False]
    assert mixed.end == date(2026, 10, 16)


def test_label():
    assert parse_session_folder_dates("2026-09-4+9 X").label() == "2026-09-04 + 2026-09-09"
    assert parse_session_folder_dates("2026-08-31..1 X").label() == "2026-08-31 .. 2026-09-01"
    assert parse_session_folder_dates("2026-09-15 X").label() == "2026-09-15"
    assert parse_session_folder_dates("2026-10-12+14..16 X").label() == "2026-10-12 + 2026-10-14 .. 2026-10-16"


def test_find_session_folder_new_patterns(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_FOLDER", str(tmp_path))
    nice = tmp_path / "2026-09-4+9 AI@Nice"
    adobe = tmp_path / "2026-08-31..1 AI@Adobe"
    nice.mkdir()
    adobe.mkdir()
    assert find_session_folder(date(2026, 9, 1))[0] == adobe
    assert find_session_folder(date(2026, 9, 4))[0] == nice
    assert find_session_folder(date(2026, 9, 9))[0] == nice
    assert find_session_folder(date(2026, 9, 5)) == (None, None)
