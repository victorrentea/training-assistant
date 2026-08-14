"""Canonical emoji catalog — the single source of truth for reactions.

The participant UI renders its reaction bar from this list (delivered via the
``/state`` bootstrap), and the daemon validates incoming reactions against it.
Defining the list here and nowhere else keeps the rendered buttons and the
accepted set from drifting apart. Do NOT duplicate this list in JavaScript.
"""
from typing import Literal

from pydantic import BaseModel


class EmojiDef(BaseModel):
    """One reaction the UI offers.

    ``emoji`` is the value that is sent and validated. ``title`` is the hover
    tooltip — an empty string means the glyph speaks for itself and the UI shows
    no tooltip. ``section`` drives placement in the participant bar; ``badge``
    is a presentation-only overlay glyph (the "can't see your screen" button
    shows 🖥️ with a small ❌, but sends plain 🖥️).
    """

    emoji: str
    title: str
    section: Literal["primary", "signal", "overflow"]
    badge: str | None = None


# Display order matters: this is the order the participant bar renders.
EMOJI_CATALOG: list[EmojiDef] = [
    # Self-explanatory glyphs carry an empty title on purpose: no tooltip at all.
    EmojiDef(emoji="❤️", title="", section="primary"),
    EmojiDef(emoji="☕", title="I need a coffee break", section="primary"),
    EmojiDef(emoji="👍", title="", section="primary"),
    EmojiDef(emoji="🔥", title="", section="primary"),
    EmojiDef(emoji="🤔", title="That's interesting...", section="primary"),
    EmojiDef(emoji="🖥️", title="I can't see your screen.", section="signal", badge="❌"),
    EmojiDef(emoji="👏", title="Applause!", section="overflow"),
    EmojiDef(emoji="⚔️", title="Let's debate this!", section="overflow"),
    EmojiDef(emoji="😂", title="I'm dead 💀", section="overflow"),
    EmojiDef(emoji="🤯", title="Mind-blowing!", section="overflow"),
    EmojiDef(emoji="🍕", title="Pizza time!", section="overflow"),
    EmojiDef(emoji="💡", title="Wait, I have an idea!", section="overflow"),
    EmojiDef(emoji="✅", title="Agreed. 100%.", section="overflow"),
    EmojiDef(emoji="❌", title="Nope. Disagree", section="overflow"),
]

# Whitelist used to gate incoming reactions — derived, never hand-maintained.
ALLOWED_EMOJI: frozenset[str] = frozenset(e.emoji for e in EMOJI_CATALOG)
