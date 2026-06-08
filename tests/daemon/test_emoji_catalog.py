"""Tests for the emoji catalog — the single source of truth for reactions."""

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


def test_every_entry_has_emoji_and_title():
    for entry in EMOJI_CATALOG:
        assert entry.emoji.strip(), f"empty emoji in {entry!r}"
        assert entry.title.strip(), f"empty title for {entry.emoji!r}"


def test_sections_are_known():
    for entry in EMOJI_CATALOG:
        assert entry.section in {"primary", "signal", "overflow"}


def test_signal_entry_present_with_badge():
    signal = [e for e in EMOJI_CATALOG if e.section == "signal"]
    assert signal, "expected a signal entry (the 'can't see your screen' button)"
    assert all(e.badge for e in signal), "signal entries carry a presentation badge"
