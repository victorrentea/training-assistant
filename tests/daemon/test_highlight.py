"""Tests for daemon.summary.highlight — the race-safe <mark> resolver."""
from daemon.summary.highlight import (
    APPLIED,
    MARK_CLOSE,
    MARK_OPEN,
    REJECTED,
    RELOCATED,
    HighlightAnchor,
    apply_highlight,
    compute_rev,
)


def test_compute_rev_is_deterministic_and_content_sensitive():
    assert compute_rev("hello") == compute_rev("hello")
    assert compute_rev("hello") != compute_rev("hello ")


def test_fast_path_applies_at_offsets():
    md = "alpha beta gamma"
    anchor = HighlightAnchor(
        exact="beta", prefix="alpha ", suffix=" gamma",
        start=6, end=10, base_rev=compute_rev(md),
    )
    r = apply_highlight(md, anchor)
    assert r.status == APPLIED
    assert r.markdown == "alpha <mark>beta</mark> gamma"
    assert r.at == 6


def test_concurrent_edit_relocates_by_quote():
    # UI rendered from md0; offsets are for md0. Then an AI prepended text.
    md0 = "alpha beta gamma"
    anchor = HighlightAnchor(
        exact="beta", prefix="alpha ", suffix=" gamma",
        start=6, end=10, base_rev=compute_rev(md0),
    )
    current = "XXX inserted. alpha beta gamma"
    r = apply_highlight(current, anchor)
    assert r.status == RELOCATED
    assert r.markdown == "XXX inserted. alpha <mark>beta</mark> gamma"


def test_ambiguous_disambiguated_by_context():
    md = "the cat sat. the cat ran."
    anchor = HighlightAnchor(exact="cat", prefix="the ", suffix=" ran")  # 2nd cat
    r = apply_highlight(md, anchor)
    assert r.status == RELOCATED
    assert r.markdown == "the cat sat. the <mark>cat</mark> ran."


def test_ambiguous_falls_back_to_nearest_offset():
    md = "x cat y cat z"
    # no context; offset near the second "cat" (index 8)
    anchor = HighlightAnchor(exact="cat", start=8)
    r = apply_highlight(md, anchor)
    assert r.markdown == "x cat y <mark>cat</mark> z"


def test_missing_passage_is_rejected_and_unchanged():
    md = "hello world"
    anchor = HighlightAnchor(exact="zzz", start=3, base_rev=compute_rev(md))
    r = apply_highlight(md, anchor)
    assert r.status == REJECTED
    assert r.markdown == md
    assert r.at is None


def test_stale_offsets_but_matching_exact_still_lands_right():
    # base_rev mismatches (someone edited elsewhere) and offsets are wrong,
    # but the exact text is still uniquely present.
    md = "prefix changed. target here."
    anchor = HighlightAnchor(exact="target", start=999, base_rev="deadbeef")
    r = apply_highlight(md, anchor)
    assert r.status == RELOCATED
    assert r.markdown == "prefix changed. <mark>target</mark> here."


def test_mark_never_straddles_bold_delimiters():
    md = "a **b** c"
    anchor = HighlightAnchor(exact=md, start=0, end=len(md), base_rev=compute_rev(md))
    r = apply_highlight(md, anchor)
    # ** delimiters preserved, and never captured inside a <mark>
    assert r.markdown.count("**") == 2
    assert MARK_OPEN + "**" not in r.markdown
    assert "**" + MARK_CLOSE not in r.markdown
    assert r.markdown == "<mark>a </mark>**<mark>b</mark>**<mark> c</mark>"


def test_mark_keeps_link_url_bare_and_highlights_only_text():
    md = "go [Playwright](https://playwright.dev) now"
    anchor = HighlightAnchor(exact=md, start=0, end=len(md), base_rev=compute_rev(md))
    r = apply_highlight(md, anchor)
    # the URL and link syntax stay outside any mark
    assert "](https://playwright.dev)" in r.markdown
    assert MARK_OPEN + "https" not in r.markdown
    # the link text is highlighted
    assert "[<mark>Playwright</mark>](https://playwright.dev)" in r.markdown


def test_idempotent_when_already_marked():
    md = "a <mark>beta</mark> c"
    anchor = HighlightAnchor(exact="beta", start=8, end=12, base_rev=compute_rev(md))
    r = apply_highlight(md, anchor)
    assert r.markdown == md  # no double-wrap
