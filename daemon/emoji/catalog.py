"""Canonical emoji catalog — the single source of truth for reactions.

The participant UI renders its reaction bar from this list (delivered via the
``/state`` bootstrap), and the daemon validates incoming reactions against it.
Defining the list here and nowhere else keeps the rendered buttons and the
accepted set from drifting apart. Do NOT duplicate this list in JavaScript.
"""
from typing import Literal

from pydantic import BaseModel, model_validator


class EmojiDef(BaseModel):
    """One reaction the UI offers.

    ``emoji`` is the value that is sent and validated. ``title`` is the hover
    tooltip — an empty string means the glyph speaks for itself and the UI shows
    no tooltip. ``section`` drives placement in the participant bar:

    - ``primary`` — a base button on the bar;
    - ``stacked`` — hidden in the vertical stack that opens above its base
      button (hover on desktop, press-and-hold on phones); ``stack_of`` names
      that base (a ``primary`` emoji). Stack order is catalog order, bottom→top;
    - ``signal`` — a stand-alone button after the separator.

    ``badge`` is a presentation-only overlay glyph (the "can't see your screen"
    button shows 🖥️ with a small ❌, but sends plain 🖥️).
    """

    emoji: str
    title: str
    section: Literal["primary", "stacked", "signal"]
    stack_of: str | None = None
    badge: str | None = None

    @model_validator(mode="after")
    def _stack_of_only_on_stacked(self) -> "EmojiDef":
        if (self.section == "stacked") != (self.stack_of is not None):
            raise ValueError("stack_of is required on, and only on, a 'stacked' entry")
        return self


# Display order matters: this is the order the participant bar renders, and
# within a stack the first entry sits closest to its base button.
EMOJI_CATALOG: list[EmojiDef] = [
    # Self-explanatory glyphs carry an empty title on purpose: no tooltip at all.
    # ❤️ — positive emotions
    EmojiDef(emoji="❤️", title="", section="primary"),
    EmojiDef(emoji="🔥", title="", section="stacked", stack_of="❤️"),
    EmojiDef(emoji="👏", title="Applause!", section="stacked", stack_of="❤️"),
    EmojiDef(emoji="😂", title="I'm dead 💀", section="stacked", stack_of="❤️"),
    # ☕ — breaks
    EmojiDef(emoji="☕", title="I need a coffee break", section="primary"),
    EmojiDef(emoji="🍕", title="Pizza time!", section="stacked", stack_of="☕"),
    # 👍 — opinion: agree / disagree / let's debate
    EmojiDef(emoji="👍", title="", section="primary"),
    EmojiDef(emoji="✅", title="Agreed. 100%.", section="stacked", stack_of="👍"),
    EmojiDef(emoji="❌", title="Nope. Disagree", section="stacked", stack_of="👍"),
    EmojiDef(emoji="⚔️", title="Let's debate this!", section="stacked", stack_of="👍"),
    # 🤔 — thinking: idea / mind-blown / sad-lost
    EmojiDef(emoji="🤔", title="That's interesting...", section="primary"),
    EmojiDef(emoji="💡", title="Wait, I have an idea!", section="stacked", stack_of="🤔"),
    EmojiDef(emoji="🤯", title="Mind-blowing!", section="stacked", stack_of="🤔"),
    EmojiDef(emoji="😢", title="That's sad / I'm lost", section="stacked", stack_of="🤔"),
    # Stays on its own: the "I can't see your screen" signal.
    EmojiDef(emoji="🖥️", title="I can't see your screen.", section="signal", badge="❌"),
]

# Whitelist used to gate incoming reactions — derived, never hand-maintained.
ALLOWED_EMOJI: frozenset[str] = frozenset(e.emoji for e in EMOJI_CATALOG)
