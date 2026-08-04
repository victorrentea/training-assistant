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
RESERVED_TRAINER_NAME = "Victor (trainer)"


def is_reserved_trainer_name(name: str | None) -> bool:
    """True if `name` collides with the reserved trainer name after normalization.

    Uses the same normalizer as the duplicate check, so case, spacing and
    Unicode variants ("victor  (TRAINER)") cannot slip past the gate.
    """
    if not name:
        return False
    return normalize_for_dedup(name) == normalize_for_dedup(RESERVED_TRAINER_NAME)


def normalize_for_dedup(name: str | None) -> str:
    """Comparison key for the soft duplicate check: casefold + NFC + collapsed.

    Matches the client's post-sanitization view of a name so server dedup and
    the client's in-session duplicate indicator agree.
    """
    if not name:
        return ""
    collapsed = " ".join(str(name).split())
    return unicodedata.normalize("NFC", collapsed).casefold()
