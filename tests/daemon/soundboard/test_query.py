"""Played shorts: the Video Snippets play log joined with the YouTube ledger."""

import json
from datetime import datetime
from pathlib import Path

from daemon.soundboard import plays, query

FIX = Path(__file__).parent / "fixtures"
LOG, LEDGER = FIX / "plays.jsonl", FIX / "youtube-publish.json"


def _moments(start="2026-10-22T10:00+03:00", end="2026-10-22T11:00+03:00"):
    return plays.moments_between(datetime.fromisoformat(start), datetime.fromisoformat(end),
                                 play_log=LOG, ledger_file=LEDGER)


def test_a_restart_within_seconds_is_one_moment():
    first = _moments()[0]
    assert (first.id, first.plays, first.at) == ("KD_1Z8iUDho", 2, "10:15")


def test_url_and_caption_come_from_the_ledger():
    first = _moments()[0]
    assert first.url == "https://youtu.be/bA-wE2QVQzE"
    assert first.caption == "Argentina — Don't cry for me, Argentina"
    assert first.title == "Argentina"


def test_unpublished_snippet_has_no_url():
    json_moment = [m for m in _moments() if m.id == "jsonClip"][0]
    assert json_moment.url is None and json_moment.kind == "soundtrack"


def test_heard_is_time_to_next_play_capped_at_the_auto_kill():
    by_id = {m.id: m for m in _moments()}
    assert by_id["KD_1Z8iUDho"].heard_s == 60.0 and not by_id["KD_1Z8iUDho"].stopped   # next play 25 min later
    assert by_id["rR4n-0KYeKQ"].heard_s == 20.0 and by_id["rR4n-0KYeKQ"].stopped       # cut by the JSON play


def test_window_filters_by_first_play_and_malformed_lines_are_skipped():
    assert [m.id for m in _moments()] == ["KD_1Z8iUDho", "rR4n-0KYeKQ", "jsonClip"]
    assert [m.id for m in _moments("2026-10-22T11:00+03:00", "2026-10-22T13:00+03:00")] == ["maltaClip"]


def test_missing_inputs_degrade_to_nothing(tmp_path):
    assert plays.moments_between(datetime(2026, 10, 22), datetime(2026, 10, 23),
                                 play_log=tmp_path / "none.jsonl", ledger_file=tmp_path / "none.json") == []


def test_cli_json_document(capsys):
    rc = query.main(["2026-10-22T10:00+03:00", "2026-10-22T11:00+03:00",
                     "--play-log", str(LOG), "--ledger", str(LEDGER), "--json"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert [m["id"] for m in doc["moments"]] == ["KD_1Z8iUDho", "rR4n-0KYeKQ", "jsonClip"]
