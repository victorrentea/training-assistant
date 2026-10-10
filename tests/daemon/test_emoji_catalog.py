"""Tests for the emoji catalog — the single source of truth for reactions."""

import pytest
from pydantic import ValidationError

from daemon.emoji.catalog import ALLOWED_EMOJI, EMOJI_CATALOG, EmojiDef


def test_catalog_is_non_empty():
    assert len(EMOJI_CATALOG) > 0
    assert all(isinstance(e, EmojiDef) for e in EMOJI_CATALOG)


def test_allowed_emoji_derived_from_catalog():
    assert ALLOWED_EMOJI == frozenset(e.emoji for e in EMOJI_CATALOG)
    # Every catalog emoji is accepted; an arbitrary one is not.
    for entry in EMOJI_CATALOG:
        assert entry.emoji in ALLOWED_EMOJI
    assert "🎉" not in ALLOWED_EMOJI


def test_stacked_emoji_are_accepted():
    """A stacked emoji is a real reaction, not decoration: the daemon must take it."""
    for emoji in ("🔥", "👏", "😂", "🍕", "✅", "❌", "⚔️", "💡", "🤯", "😢"):
        assert emoji in ALLOWED_EMOJI


def test_emoji_are_unique():
    emojis = [e.emoji for e in EMOJI_CATALOG]
    assert len(emojis) == len(set(emojis))


def test_every_entry_has_emoji():
    for entry in EMOJI_CATALOG:
        assert entry.emoji.strip(), f"empty emoji in {entry!r}"


def test_titles_are_either_meaningful_or_deliberately_absent():
    """An empty title is allowed — it means "self-explanatory, show no tooltip"."""
    for entry in EMOJI_CATALOG:
        assert entry.title == entry.title.strip(), f"padded title for {entry.emoji!r}"


def test_sections_are_known():
    for entry in EMOJI_CATALOG:
        assert entry.section in {"primary", "stacked", "signal"}


def test_bar_groups_as_designed():
    """Four base emoji on the bar, each with its stack (bottom→top), plus the signal."""
    bases = [e.emoji for e in EMOJI_CATALOG if e.section == "primary"]
    assert bases == ["❤️", "☕", "👍", "🤔"]
    stacks = {b: [e.emoji for e in EMOJI_CATALOG if e.stack_of == b] for b in bases}
    assert stacks == {
        "❤️": ["🔥", "👏", "😂"],
        "☕": ["🍕"],
        "👍": ["✅", "❌", "⚔️"],
        "🤔": ["💡", "🤯", "😢"],
    }


def test_every_stacked_entry_points_at_a_primary_base():
    bases = {e.emoji for e in EMOJI_CATALOG if e.section == "primary"}
    for entry in EMOJI_CATALOG:
        if entry.section == "stacked":
            assert entry.stack_of in bases, f"{entry.emoji!r} stacks on a non-base {entry.stack_of!r}"
        else:
            assert entry.stack_of is None


def test_stack_of_is_rejected_outside_a_stack():
    with pytest.raises(ValidationError):
        EmojiDef(emoji="🔥", title="", section="primary", stack_of="❤️")
    with pytest.raises(ValidationError):
        EmojiDef(emoji="🔥", title="", section="stacked")


def test_signal_entry_present_with_badge():
    signal = [e for e in EMOJI_CATALOG if e.section == "signal"]
    assert signal, "expected a signal entry (the 'can't see your screen' button)"
    assert all(e.badge for e in signal), "signal entries carry a presentation badge"
    assert all(e.stack_of is None for e in signal)
