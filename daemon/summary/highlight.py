"""Deterministic, race-safe application of ``<mark>`` highlights to ai-summary.md.

The host selects a passage in the rendered summary and the UI sends a *text-quote
anchor* — the selected source substring (``exact``) plus a little surrounding
context (``prefix``/``suffix``), the source offsets it came from (``start``/
``end``), and ``base_rev`` (a hash of the markdown the UI rendered from).

This module resolves that anchor against the **current** markdown at write time
and returns the markdown with ``<mark>…</mark>`` inserted — or a *rejection* if
the passage has moved or changed. That is what makes it safe against a concurrent
writer (an AI editing the same ``ai-summary.md`` at the same moment): stale
offsets never scramble the file, they either relocate by snippet or fail cleanly.

Resolution order:
  1. **Fast path** — ``base_rev`` matches the current file *and* the offsets still
     spell ``exact`` → wrap at those offsets.
  2. **Relocate** — otherwise find every occurrence of ``exact`` in the current
     file and pick the one whose *actual* surrounding text best matches the
     anchor's ``prefix``/``suffix`` (scored by how many characters of context
     agree), using the original ``start`` offset only as a tiebreaker. This
     honours the anchor even when the surrounding markdown has drifted slightly
     (a concurrent writer reworded a neighbour), which a rigid ``prefix+exact+
     suffix`` substring match would miss — and it keeps a repeated short word
     (``context`` …) from collapsing onto the first occurrence.
  3. **Reject** — ``exact`` not present at all → return the markdown unchanged
     with a reason.

The insertion also snaps ``<mark>`` boundaries so a mark never straddles a
markdown inline token (``**bold**`` / ``*italic*`` / `` `code` `` / ``[t](url)``),
which would otherwise emit malformed nesting like
``<strong>…<mark>…</strong>…</mark>``.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

MARK_OPEN = "<mark>"
MARK_CLOSE = "</mark>"

# Applied at the requested offsets (nothing moved under us).
APPLIED = "applied"
# Offsets were stale (a concurrent edit shifted the text) but the passage was
# re-found by its text-quote anchor.
RELOCATED = "relocated"
# The passage no longer exists verbatim — caller should ask the host to re-select.
REJECTED = "rejected"


def compute_rev(text: str) -> str:
    """Content revision of the markdown — cheap optimistic-concurrency token."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HighlightAnchor:
    exact: str
    prefix: str = ""
    suffix: str = ""
    start: int | None = None
    end: int | None = None
    base_rev: str | None = None


@dataclass(frozen=True)
class HighlightResult:
    status: str          # APPLIED | RELOCATED | REJECTED
    markdown: str        # new markdown (unchanged when REJECTED)
    at: int | None = None    # start offset in the *original* markdown where wrapped
    reason: str = ""


def _all_indices(haystack: str, needle: str) -> list[int]:
    if not needle:
        return []
    out: list[int] = []
    i = haystack.find(needle)
    while i != -1:
        out.append(i)
        i = haystack.find(needle, i + 1)  # allow overlaps; harmless for our text
    return out


def _common_suffix_len(a: str, b: str) -> int:
    """How many trailing characters ``a`` and ``b`` share (from the right)."""
    n, la, lb = 0, len(a), len(b)
    limit = min(la, lb)
    while n < limit and a[la - 1 - n] == b[lb - 1 - n]:
        n += 1
    return n


def _common_prefix_len(a: str, b: str) -> int:
    """How many leading characters ``a`` and ``b`` share (from the left)."""
    n = 0
    limit = min(len(a), len(b))
    while n < limit and a[n] == b[n]:
        n += 1
    return n


def _context_score(md: str, i: int, exact: str, anchor: HighlightAnchor) -> int:
    """How well the text around occurrence ``i`` matches the anchor's context.

    The anchor's ``prefix``/``suffix`` are the source text that *immediately*
    surrounded the selection, so the strongest signal is how many characters of
    the prefix agree with the text ending at ``i`` (compared right-to-left) plus
    how many characters of the suffix agree with the text starting after the
    occurrence (left-to-right). Partial agreement still counts, so a neighbour
    reworded by a concurrent writer degrades the score gracefully instead of
    dropping the occurrence entirely.
    """
    before = md[:i]
    after = md[i + len(exact):]
    return (
        _common_suffix_len(anchor.prefix, before)
        + _common_prefix_len(anchor.suffix, after)
    )


def _pick_occurrence(md: str, hits: list[int], exact: str, anchor: HighlightAnchor) -> int:
    """Choose the occurrence of ``exact`` the anchor points at.

    Primary key: most surrounding context in common with ``prefix``/``suffix``.
    Tiebreaker: nearest to the anchor's original ``start`` offset. Final
    tiebreaker: earliest occurrence — so the result is fully deterministic.
    """
    if len(hits) == 1:
        return hits[0]

    def key(i: int) -> tuple[int, int, int]:
        score = _context_score(md, i, exact, anchor)
        dist = abs(i - anchor.start) if anchor.start is not None else 0
        return (-score, dist, i)  # max score, then min distance, then earliest

    return min(hits, key=key)


def _find_span(md: str, anchor: HighlightAnchor) -> tuple[int, int, str] | None:
    """Locate the (start, end, status) of ``exact`` in the current markdown."""
    exact = anchor.exact
    if not exact:
        return None

    # 1) Fast path: base_rev proves the file is unchanged and offsets still fit.
    if (
        anchor.base_rev is not None
        and anchor.start is not None
        and anchor.end is not None
        and 0 <= anchor.start <= anchor.end <= len(md)
        and anchor.base_rev == compute_rev(md)
        and md[anchor.start:anchor.end] == exact
    ):
        return (anchor.start, anchor.end, APPLIED)

    # 2) Relocate: among every occurrence of `exact`, pick the one whose actual
    #    surrounding text best matches the anchor's prefix/suffix (start offset
    #    only breaks ties). Using prefix/suffix as a *soft* per-occurrence score
    #    — rather than requiring a rigid contiguous `prefix+exact+suffix` match —
    #    disambiguates a repeated short word robustly even when a neighbour has
    #    drifted, instead of collapsing onto the first occurrence.
    hits = _all_indices(md, exact)
    if hits:
        s = _pick_occurrence(md, hits, exact, anchor)
        return (s, s + len(exact), RELOCATED)

    # 3) Reject: the passage no longer exists verbatim.
    return None


# One inline link, an emphasis/strike/code delimiter run, or a run of plain text.
_TOKEN = re.compile(
    r"(?P<link>\[[^\]\n]*\]\([^)\n]*\))"
    r"|(?P<delim>\*\*\*|\*\*|\*|~~|`)"
    r"|(?P<text>[^*~`\[]+)"
    r"|(?P<other>.)",
    re.DOTALL,
)


def _wrap_text(s: str) -> str:
    return MARK_OPEN + s + MARK_CLOSE if s else ""


def _mark_region(region: str) -> str:
    """Wrap the visible text of ``region`` in ``<mark>`` without straddling any
    markdown inline token. Delimiters (`**`, `*`, `~~`, `` ` ``) and link
    syntax/URLs stay outside the marks; only rendered text is wrapped."""
    out: list[str] = []
    for m in _TOKEN.finditer(region):
        if m.lastgroup == "link":
            # [text](url) -> keep brackets/url bare, highlight only the link text
            inner = m.group()
            close = inner.index("](")
            out.append("[" + _wrap_text(inner[1:close]) + inner[close:])
        elif m.lastgroup == "text":
            out.append(_wrap_text(m.group()))
        else:  # delim / other -> emit unchanged, never wrapped
            out.append(m.group())
    return "".join(out)


def _already_marked(md: str, s: int, e: int) -> bool:
    """True if [s, e) is already immediately wrapped by a mark (idempotence)."""
    return md[max(0, s - len(MARK_OPEN)):s] == MARK_OPEN and md[e:e + len(MARK_CLOSE)] == MARK_CLOSE


def apply_highlight(markdown: str, anchor: HighlightAnchor) -> HighlightResult:
    """Resolve ``anchor`` against ``markdown`` and return the marked result."""
    found = _find_span(markdown, anchor)
    if not found:
        return HighlightResult(REJECTED, markdown, None, "passage not found — re-select")
    s, e, status = found
    if _already_marked(markdown, s, e):
        return HighlightResult(status, markdown, s, "already highlighted")
    new_md = markdown[:s] + _mark_region(markdown[s:e]) + markdown[e:]
    return HighlightResult(status, new_md, s, "")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def apply_highlight_to_file(path: str | Path, anchor: HighlightAnchor) -> HighlightResult:
    """Read the summary file, apply the highlight, and atomically write it back.

    Re-reads the file just before writing: if a concurrent writer (e.g. an AI
    editing ``ai-summary.md``) changed it since we read, the anchor is re-resolved
    against the *fresh* content — so the concurrent edit is folded in and its
    passage relocated (or cleanly rejected) rather than clobbered. The write
    itself is an atomic ``os.replace`` (whole-file swap, no partial state).
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HighlightResult(REJECTED, "", None, "summary file not found")

    result = apply_highlight(text, anchor)
    if result.status == REJECTED or result.markdown == text:
        return result

    current = p.read_text(encoding="utf-8")
    if current != text:  # a concurrent edit landed — re-resolve on fresh content
        result = apply_highlight(current, anchor)
        if result.status == REJECTED or result.markdown == current:
            return result

    _atomic_write(p, result.markdown)
    return result
