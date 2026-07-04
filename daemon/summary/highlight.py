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
  2. **Relocate** — otherwise search the current file for ``prefix+exact+suffix``
     (then ``exact`` alone); unique → wrap there, multiple → the occurrence
     nearest the original offset.
  3. **Reject** — not found → return the markdown unchanged with a reason.

The insertion also snaps ``<mark>`` boundaries so a mark never straddles a
markdown inline token (``**bold**`` / ``*italic*`` / `` `code` `` / ``[t](url)``),
which would otherwise emit malformed nesting like
``<strong>…<mark>…</strong>…</mark>``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

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


def _pick_nearest(indices: list[int], target: int | None) -> int:
    if target is None:
        return indices[0]
    return min(indices, key=lambda i: abs(i - target))


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

    # 2) Relocate by the full text-quote (prefix+exact+suffix) — most specific.
    if anchor.prefix or anchor.suffix:
        quote = anchor.prefix + exact + anchor.suffix
        hits = _all_indices(md, quote)
        if hits:
            base = _pick_nearest(hits, anchor.start)
            s = base + len(anchor.prefix)
            return (s, s + len(exact), RELOCATED)

    # 3) Relocate by exact alone — nearest occurrence to the original offset.
    hits = _all_indices(md, exact)
    if hits:
        s = _pick_nearest(hits, anchor.start)
        return (s, s + len(exact), RELOCATED)

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
