import json
from pathlib import Path

import pytest

from daemon.wiki import topic_frequency as tf


def _note(session: Path, name: str, text: str) -> None:
    path = session / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Three past sessions, today's, and a later one that must not count."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TRAINING_ASSISTANTS_SECRETS_FILE", str(tmp_path / "no-secrets.env"))
    monkeypatch.delenv("LLM_ADAPTER", raising=False)
    _note(tmp_path / "2026-06-22+25 AI@Kambi", "Skills.md", "# Skills\n\nA skill lazy-loads rules.\n")
    _note(tmp_path / "2026-06-22+25 AI@Kambi", "Home.md", "# Home\n\n[[Skills]]\n")
    _note(tmp_path / "2026-07-01 AI@CodeLab", "skills.md", "Skills load on demand.\n")
    _note(tmp_path / "2026-07-01 AI@CodeLab", "Hooks.md", "Hooks run on agent events.\n")
    _note(tmp_path / "2026-09-10..11 Testing@DB", "Skill-uri.md", "Un skill se încarcă la nevoie.\n")
    (tmp_path / "2026-08-01 AI@NoWiki").mkdir()
    _note(tmp_path / "2026-10-20 AI@Later", "Brand new.md", "Later.\n")
    today = tmp_path / "2026-10-09 AI@JAX.London"
    _note(today, "Skills.md", "---\ntags: [x]\n---\n# Skills\n\n**A skill fires on its [[Front matter|description]].**\n\n- more\n")
    _note(today, "Hooks.md", "Hooks guard tool calls.\n")
    _note(today, "Brand new idea.md", "Something never taught before.\n")
    _note(today, "Home.md", "# Home\n")
    _note(today, "2026-10-09.md", "")
    return tmp_path


def _fake_claude(calls):
    """Matches by keyword, like the real model would by topic."""

    def call(api_key, past_block, current_block):
        calls.append((past_block, current_block))
        past = {int(line.split(".")[0][1:]): line for line in past_block.splitlines() if line.startswith("P")}
        matches = []
        for line in current_block.splitlines():
            if not line.startswith("C"):
                continue
            number = int(line.split(".")[0][1:])
            word = "skill" if "Skills" in line else "hook" if "Hooks" in line else None
            hits = [p for p, text in past.items() if word and word in text.lower()]
            matches.append({"note": number, "past": hits})
        return {"matches": matches}, {"input": 1000, "cache_write": 5000, "cache_read": 0, "output": 200}

    return call


def test_counts_distinct_past_sessions_per_note(root, monkeypatch):
    calls = []
    monkeypatch.setattr(tf, "call_claude", _fake_claude(calls))
    seen, sessions = tf.score(root / "2026-10-09 AI@JAX.London")
    # 3 past sessions with a wiki; the later one and the one without a wiki don't count.
    assert sessions == 3
    # "Skills" and "skills" are one past topic, "Skill-uri" another: 3 distinct sessions.
    assert seen == {"Skills": 3, "Hooks": 1, "Brand-new-idea": 0}
    past_block, current_block = calls[0]
    assert "Home" not in past_block and "Home" not in current_block
    assert "2026-10-09" not in current_block  # empty note
    assert "Brand new." not in past_block  # the later session
    assert "C1. Brand new idea — Something never taught before." in current_block
    assert "A skill fires on its description." in current_block


def test_scores_are_cached_and_only_new_or_renamed_notes_are_asked(root, monkeypatch):
    today = root / "2026-10-09 AI@JAX.London"
    calls = []
    monkeypatch.setattr(tf, "call_claude", _fake_claude(calls))
    tf.score(today)
    cache = json.loads((today / "wiki-cache" / "topic-frequency.json").read_text())
    assert cache["notes"]["Skills"] == {"title": "Skills", "seen": 3}

    seen, _ = tf.score(today)
    assert len(calls) == 1  # nothing new: no call
    assert seen["Skills"] == 3

    _note(today, "Sandboxing.md", "Run the agent in a box.\n")
    tf.score(today)
    assert len(calls) == 2
    assert "Sandboxing" in calls[1][1] and "Skills" not in calls[1][1]


def test_cache_is_dropped_when_the_past_sessions_change(root, monkeypatch):
    today = root / "2026-10-09 AI@JAX.London"
    calls = []
    monkeypatch.setattr(tf, "call_claude", _fake_claude(calls))
    tf.score(today)
    _note(root / "2026-10-07 Agentic keynote", "Skills.md", "Skills again.\n")
    seen, sessions = tf.score(today)
    assert len(calls) == 2 and sessions == 4
    assert seen["Skills"] == 4


def test_api_failure_leaves_notes_unscored_and_retries_next_build(root, monkeypatch):
    today = root / "2026-10-09 AI@JAX.London"

    def boom(*_):
        raise RuntimeError("credit balance too low")

    monkeypatch.setattr(tf, "call_claude", boom)
    assert tf.score(today) == ({}, 3)
    assert not (today / "wiki-cache").exists()

    calls = []
    monkeypatch.setattr(tf, "call_claude", _fake_claude(calls))
    assert tf.score(today)[0]["Skills"] == 3


def test_no_api_key_means_no_call_and_no_glow(root, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(tf, "call_claude", lambda *_: pytest.fail("must not call Claude"))
    assert tf.score(root / "2026-10-09 AI@JAX.London") == ({}, 3)


def test_stub_adapter_never_calls_claude(root, monkeypatch):
    monkeypatch.setenv("LLM_ADAPTER", "stub")
    monkeypatch.setattr(tf, "call_claude", lambda *_: pytest.fail("must not call Claude"))
    assert tf.score(root / "2026-10-09 AI@JAX.London")[0] == {}


def test_write_note_glow_never_breaks_the_build(root, monkeypatch, tmp_path):
    monkeypatch.setattr(tf, "score", lambda _folder: (_ for _ in ()).throw(OSError("disk")))
    out = tmp_path / "out"
    out.mkdir()
    tf.write_note_glow(root / "2026-10-09 AI@JAX.London" / "wiki", out)
    assert json.loads((out / tf.GLOW_FILE).read_text()) == {"sessions": 0, "seen": {}}


def test_write_note_glow_writes_counts_and_session_total(root, monkeypatch, tmp_path):
    monkeypatch.setattr(tf, "call_claude", _fake_claude([]))
    out = tmp_path / "out"
    out.mkdir()
    tf.write_note_glow(root / "2026-10-09 AI@JAX.London" / "wiki", out)
    glow = json.loads((out / tf.GLOW_FILE).read_text())
    assert glow == {"sessions": 3, "seen": {"Skills": 3, "Hooks": 1, "Brand-new-idea": 0}}


@pytest.mark.parametrize(
    "path, slug",
    [("Skills", "Skills"), ("talks/Spec driven", "talks/Spec-driven"), ("Q&A?", "Q-and-A"), ("100% #1", "100-percent-1")],
)
def test_slugs_match_quartz(path, slug):
    assert tf.quartz_slug(path) == slug


@pytest.mark.parametrize(
    "name, day",
    [("2026-09-21..23 Arch@DB", (2026, 9, 21)), ("2026-09-4+9 AI@Nice", (2026, 9, 4)), ("e2e-test", None)],
)
def test_session_date_is_the_first_day(name, day):
    parsed = tf.session_date(name)
    assert (parsed and (parsed.year, parsed.month, parsed.day)) == day


def test_cost_uses_haiku_prices():
    usage = {"input": 1_000_000, "cache_write": 1_000_000, "cache_read": 1_000_000, "output": 1_000_000}
    assert tf.cost_usd(usage) == pytest.approx(0.10 + 0.125 + 0.01 + 0.50)
