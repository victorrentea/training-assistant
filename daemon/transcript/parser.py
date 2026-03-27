"""Transcript line parsing and classification.

Regex patterns, noise-word sets, speaker detection, and low-signal filtering.
"""

from __future__ import annotations

import re


_SPEAKER_RE = re.compile(r"^([^:\t\n\r]{1,40}):\s*(.*)$")
_PARENS_ONLY_RE = re.compile(r"^(?:\([^)]*\)\s*)+$")

_LOW_SIGNAL_SINGLE_WORDS = {
    "music",
    "silence",
    "inaudible",
    "blank",
    "audio",
    "foreign",
    "romanian",
    "russian",
    "beep",
    "beeping",
    "homing",
    "you",
}
_LOW_SIGNAL_PREFIXES = (
    "silence from",
    "silence for",
    "pause for group work",
    "speaking in foreign language",
    "foreign language spoken",
    "side conversation",
    "break in audio",
    "no speech",
    "russian inaudible",
)
_LOW_SIGNAL_TOKEN_SET = {
    "music",
    "upbeat",
    "soft",
    "silence",
    "inaudible",
    "blank",
    "audio",
    "pause",
    "group",
    "work",
    "keyboard",
    "clicking",
    "typing",
    "beep",
    "beeping",
    "foreign",
    "language",
    "romanian",
    "russian",
    "speech",
    "no",
    "side",
    "conversation",
    "break",
    "in",
    "mouse",
    "playing",
    "you",
}


def _parse_speaker(text: str) -> tuple[str | None, str]:
    match = _SPEAKER_RE.match(text)
    if not match:
        return None, text

    speaker_candidate = match.group(1).strip().replace("\t", " ")
    content = match.group(2).strip()

    if not speaker_candidate:
        return None, text

    words = speaker_candidate.split()
    if len(words) > 3:
        return None, text
    if any(len(w) > 30 for w in words):
        return None, text

    # Keep speaker parsing conservative to avoid accidental captures like "So: ..."
    if len(words) == 1 and len(words[0]) <= 2:
        return None, text

    return speaker_candidate, content


def _is_low_signal_noise(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return True

    canonical = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    if not canonical:
        return True

    tokens = canonical.split()
    if len(tokens) == 1 and tokens[0] in _LOW_SIGNAL_SINGLE_WORDS:
        return True

    if _PARENS_ONLY_RE.match(raw):
        inner = " ".join(re.findall(r"\(([^)]*)\)", raw.lower()))
        inner_tokens = re.sub(r"[^a-z0-9]+", " ", inner).strip().split()
        if inner_tokens and all(tok in _LOW_SIGNAL_TOKEN_SET for tok in inner_tokens):
            return True

    for prefix in _LOW_SIGNAL_PREFIXES:
        if canonical.startswith(prefix) and len(tokens) <= 12:
            return True

    if len(tokens) <= 6 and all(tok in _LOW_SIGNAL_TOKEN_SET for tok in tokens):
        return True

    return False
