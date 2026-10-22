import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daemon.soundboard import presses as sb
from daemon.soundboard.query import main

FIXTURES = Path(__file__).parent / "fixtures"
RO = timezone(timedelta(hours=3))


def _moments(start="10:00", end="12:00", **overrides):
    kwargs = dict(
        press_log=FIXTURES / "presses.jsonl",
        tiles_file=FIXTURES / "tiles.json",
        captions=str(FIXTURES / "captions.json"),
        ledger_file=FIXTURES / "youtube-publish.json",
    )
    kwargs.update(overrides)
    day = "2026-10-22T"
    return sb.moments_between(
        datetime.fromisoformat(day + start).replace(tzinfo=RO),
        datetime.fromisoformat(day + end).replace(tzinfo=RO),
        **kwargs,
    )


def test_window_keeps_only_moments_whose_first_tap_is_inside():
    moments = _moments()
    assert [m.file for m in moments] == [
        "53b_7_rings.mp3",
        "62_lionel_richie.mp3",
        "53_rain.mp3",
        "61_hallelujah.mp3",
        "02_siren.mp3",
        "fx_confetti.mp3",
    ]
    assert [m.at for m in moments][:2] == ["10:15", "10:40"]


def test_stop_and_restart_within_seconds_is_one_moment_joined_with_ledger_and_captions():
    rings = _moments()[0]
    assert rings.presses == 3
    assert (rings.n, rings.layer) == (53, "b")
    assert rings.title == "7 Rings"
    assert rings.caption == "♪ I want it, I got it ♪ / ♪ I see it, I like it ♪"
    assert rings.url == "https://youtu.be/abc123"
    assert rings.visibility == "unlisted"
    assert rings.duration_s == 12.4
    # tap 1 starts, tap 2 (2.5 s later) stops, tap 3 restarts and it plays out
    assert rings.heard_s == pytest.approx(2.5 + 12.4)
    assert rings.stopped is False
    assert rings.ts == "2026-10-22T10:15:00+03:00"


def test_tap_then_immediate_stop_is_flagged_as_barely_heard():
    hello = _moments()[1]
    assert hello.title == "Hello"  # the tile's own label wins over the file name
    assert hello.presses == 2
    assert hello.stopped is True
    assert hello.heard_s == pytest.approx(1.2)
    assert hello.url is None  # not published yet


def test_restartable_tile_retap_replays_instead_of_stopping():
    rain = _moments()[2]
    assert rain.presses == 2
    assert rain.stopped is False
    assert rain.heard_s == pytest.approx(3 + 8)


def test_another_tile_cuts_the_playing_clip_short():
    hallelujah = _moments()[3]
    assert hallelujah.url == "https://youtu.be/def456"
    assert hallelujah.heard_s == pytest.approx(6.0)  # the siren 6 s later stopped it


def test_clip_off_the_grid_keeps_nulls_and_unknown_length():
    confetti = _moments()[-1]
    assert (confetti.n, confetti.layer, confetti.caption, confetti.url) == (None, None, None, None)
    assert confetti.title == "Fx Confetti"
    assert confetti.heard_s is None
    assert confetti.source == "other"


def test_missing_ledger_and_captions_degrade_to_nulls(tmp_path):
    moments = _moments(captions="", ledger_file=tmp_path / "absent.json")
    assert len(moments) == 6
    assert all(m.url is None and m.caption is None and m.duration_s is None for m in moments)
    assert moments[1].heard_s == pytest.approx(1.2)  # a stop tap needs no clip length


def test_missing_press_log_is_no_moments(tmp_path):
    assert _moments(press_log=tmp_path / "absent.jsonl") == []


def test_press_log_path_env_beats_effects_config(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"pressLogFile": str(tmp_path / "from-config.jsonl")}))
    monkeypatch.setattr(sb, "EFFECTS_CONFIG", config)
    monkeypatch.delenv("SOUNDBOARD_PRESS_LOG", raising=False)
    assert sb.press_log_path() == tmp_path / "from-config.jsonl"
    monkeypatch.setenv("SOUNDBOARD_PRESS_LOG", str(tmp_path / "from-env.jsonl"))
    assert sb.press_log_path() == tmp_path / "from-env.jsonl"


def test_press_log_path_defaults_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "EFFECTS_CONFIG", tmp_path / "absent.json")
    monkeypatch.delenv("SOUNDBOARD_PRESS_LOG", raising=False)
    assert sb.press_log_path() == sb.DEFAULT_PRESS_LOG


def _cli_args(*extra):
    return [
        "2026-10-22T10:00+03:00",
        "2026-10-22T11:00+03:00",
        "--press-log", str(FIXTURES / "presses.jsonl"),
        "--tiles", str(FIXTURES / "tiles.json"),
        "--captions", str(FIXTURES / "captions.json"),
        "--ledger", str(FIXTURES / "youtube-publish.json"),
        *extra,
    ]


def test_cli_prints_json_lines_and_summary_on_stderr(capsys):
    assert main(_cli_args()) == 0
    out, err = capsys.readouterr()
    rows = [json.loads(line) for line in out.splitlines()]
    assert [r["title"] for r in rows] == ["7 Rings", "Hello"]
    assert set(rows[0]) >= {"ts", "n", "layer", "file", "title", "caption", "url"}
    assert "moments: 2 · with url: 1" in err


def test_cli_json_document_for_prewarm(capsys):
    assert main(_cli_args("--json")) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["from"] == "2026-10-22T10:00+03:00"
    assert [m["file"] for m in doc["moments"]] == ["53b_7_rings.mp3", "62_lionel_richie.mp3"]


def test_cli_rejects_reversed_range(capsys):
    assert main(["2026-10-22T11:00", "2026-10-22T10:00"]) == 2
