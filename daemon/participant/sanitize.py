"""Participant display-name sanitization and dedup normalization.

Two pure helpers shared by the identity endpoints (register / rename):

- ``sanitize_name`` — the *ingest* filter applied before a name is stored.
  Strips control chars / NUL / ANSI escapes / Unicode bidi overrides, collapses
  internal whitespace runs to a single space, NFC-normalizes, and caps length.
  This is the single choke point so register and rename cannot diverge.

- ``normalize_for_dedup`` — the *comparison* key used by the soft duplicate
  check. casefold + NFC + collapsed whitespace so ``Alice``/``alice``, an
  NFC-vs-NFD ``José`` and double-space variants all collide.
"""
from __future__ import annotations

import re
import unicodedata

# Server-side cap on participant display names; applied AFTER sanitization so a
# name padded with control chars can't smuggle content past the limit. Mirrored
# by maxlength="64" on the participant page's name inputs.
MAX_NAME_LEN = 64

# ANSI/VT escape sequences (CSI colour codes etc.). Removed as whole units first
# so a sequence like "\x1b[31m" does not leave the printable tail "[31m" behind
# once the lone ESC control byte is stripped.
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|[@-Z\\-_])")

# Unicode bidirectional formatting overrides/isolates — a spoofing vector
# (RLO can visually reverse a name to impersonate another). Explicit ranges:
#   U+202A..U+202E  LRE RLE PDF LRO RLO
#   U+2066..U+2069  LRI RLI FSI PDI
_BIDI_OVERRIDES = frozenset(
    chr(c) for c in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))
)


def _strip_bad_chars(text: str) -> str:
    """Drop NUL, non-whitespace control chars and bidi overrides.

    Whitespace control chars (\\t \\n \\r \\f \\v …) are deliberately KEPT here
    so the subsequent whitespace-collapse turns them into a single space rather
    than silently welding two words together.
    """
    out: list[str] = []
    for ch in text:
        if ch in _BIDI_OVERRIDES:
            continue
        if unicodedata.category(ch) == "Cc" and not ch.isspace():
            continue  # NUL and other non-whitespace C0/C1 controls
        out.append(ch)
    return "".join(out)


def sanitize_name(raw: str | None) -> str:
    """Sanitize an incoming display name; returns "" for empty/all-noise input.

    Pipeline: NFC → strip ANSI escapes → strip control/bidi chars → collapse
    whitespace runs to a single space (and trim) → cap at ``MAX_NAME_LEN``.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", str(raw))
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _strip_bad_chars(text)
    # str.split() with no args splits on any Unicode whitespace run and drops
    # leading/trailing whitespace, so this both collapses and trims.
    text = " ".join(text.split())
    return text[:MAX_NAME_LEN]


# The trainer's display name is a privilege, not a string anyone may type.
# Only a UUID that claimed trainer over loopback (daemon/host_machine/router.py)
# may hold it — otherwise any participant could impersonate the trainer by
# typing it into the name field.
RESERVED_TRAINER_NAME = "🧑‍🏫 Victor Rentea"


def _spoof_key(name: str) -> str:
    """Collapse a name to what it LOOKS like, for impersonation checks.

    Deliberately stricter than normalize_for_dedup, which must keep matching the
    client's own duplicate calculation and therefore cannot change. Two extra
    steps close real bypasses found by adversarial testing:

    - drop format (Cf) characters — zero-width space/joiner and BOM survive
      sanitize_name (it strips only Cc controls) and render as nothing, so
      "🧑‍🏫 Victor​ Rentea" is visually identical to the reserved name;
    - NFKC rather than NFC — folds fullwidth "Ｖ" and Roman-numeral "Ⅴ" onto
      plain ASCII letters.

    Cyrillic homoglyphs (о, е) are NOT folded by NFKC; the confusable map below
    handles the handful that matter for this specific name.
    """
    stripped = "".join(ch for ch in str(name) if unicodedata.category(ch) != "Cf")
    # Whitespace is DROPPED, not collapsed: spacing is invisible to the eye, so
    # "🧑‍🏫Victor Rentea" (the gap after the emoji closed up) must fold onto the
    # reserved key exactly like the double-spaced variants already did. Matters
    # most next to the emoji, where a present-or-absent space reads the same.
    collapsed = "".join(stripped.split())
    return unicodedata.normalize("NFKC", collapsed).casefold()


def _wildcard_key(name: str) -> str:
    """Same as _spoof_key, but every non-ASCII character becomes a wildcard.

    A hand-curated confusables map is inherently incomplete — adversarial
    testing walked straight past a Cyrillic-only list using Greek omicron and
    Armenian oh, and the long tail (Cherokee, Coptic, …) never ends. So instead
    of enumerating lookalikes, treat ANY non-ASCII character as "could be
    passing for some ASCII letter" and compare shape.

    This blocks homoglyphs from every script at once, while genuinely different
    names survive: "Виктор (тренер)" folds to a different length than
    the reserved name and is allowed through.
    """
    return "".join(ch if ch.isascii() else "�" for ch in _spoof_key(name))


def _looks_like(candidate: str, target: str) -> bool:
    """True if candidate matches target once wildcards stand in for any letter.

    A wildcard stands in for a target character that is a letter OR is itself
    non-ASCII. The second arm is load-bearing: the reserved name carries an emoji
    prefix, and _wildcard_key blanks the candidate's emoji to "�". Matching only
    ``b.isalpha()`` would fail against an emoji target (category So, not
    alphabetic), so the reserved name would not even match ITSELF — silently
    turning the whole impersonation gate off.
    """
    c, t = _wildcard_key(candidate), _spoof_key(target)
    if len(c) != len(t):
        return False
    return all(
        a == b or (a == "�" and (b.isalpha() or not b.isascii()))
        for a, b in zip(c, t)
    )


def is_reserved_trainer_name(name: str | None) -> bool:
    """True if `name` is, or merely LOOKS like, the reserved trainer name.

    Impersonation is a visual attack, so the comparison is on appearance, not
    on bytes: case, spacing, zero-width characters, fullwidth forms and Cyrillic
    homoglyphs all collapse onto the same key.
    """
    if not name:
        return False
    return _looks_like(name, RESERVED_TRAINER_NAME)


def normalize_for_dedup(name: str | None) -> str:
    """Comparison key for the soft duplicate check: casefold + NFC + collapsed.

    Matches the client's post-sanitization view of a name so server dedup and
    the client's in-session duplicate indicator agree.
    """
    if not name:
        return ""
    collapsed = " ".join(str(name).split())
    return unicodedata.normalize("NFC", collapsed).casefold()
