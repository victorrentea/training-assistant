# Emoji Whitelist as Single Source of Truth — Design

**Date:** 2026-06-08
**Status:** Approved (brainstorming)

## Problem

A pentest finding: the participant emoji-reaction endpoint
(`POST /api/participant/emoji/reaction`) accepts any short string. Its only
guard is `not emoji or len(emoji) > 4` (`daemon/emoji/router.py:50-52`). A
crafted request therefore floats **arbitrary** emoji/characters on the host
screen and on the macOS desktop overlay.

The set of emoji the UI actually offers is hardcoded as `<button>` markup in
`static/participant.html` (the primary reaction bar + the `+` overflow menu).
Adding a Python whitelist *next to* this HTML list would duplicate the list in
two places and invite drift.

## Goal

- Enforce a whitelist at the daemon: only emoji the UI offers are accepted.
- Define that whitelist **once**, in Python — the single source of truth.
- Deliver the list to the participant page on connection so the buttons it
  renders and the set the backend accepts can never drift apart.
- **No duplicated list in JavaScript.** The frontend renders its buttons from
  the data the daemon sends; it carries no hardcoded fallback list.

## Non-goals

- No change to how emoji float on the host browser or the macOS overlay
  (those render whatever they receive; gating happens upstream at ingestion).
- No redesign of the emoji bar layout, tooltips, or promote-to-bar behavior —
  the bar must render identically to today.
- No new host-side emoji picker.

## Architecture

Single source of truth in Python → enforced at the one ingestion endpoint →
delivered to the page via the existing `/state` bootstrap → page renders its
buttons from it.

```
daemon/emoji/catalog.py  ── EMOJI_CATALOG (ordered) + ALLOWED_EMOJI (derived set)
        │                                   │
        │ (validation)                      │ (delivery)
        ▼                                   ▼
emoji/router.py  POST /reaction      participant/router.py  GET /state
  emoji ∈ ALLOWED_EMOJI ? ok : 400     response.emoji_catalog = EMOJI_CATALOG
        │                                   │
        ▼                                   ▼
  addon overlay / host WS          participant.html renderEmojiBar(catalog)
```

## Components

### 1. `daemon/emoji/catalog.py` (new)

The only place the list exists.

```python
from typing import Literal
from pydantic import BaseModel

class EmojiDef(BaseModel):
    emoji: str                                      # sent + validated value
    title: str                                      # tooltip
    section: Literal["primary", "signal", "overflow"]
    badge: str | None = None                        # presentation overlay only

EMOJI_CATALOG: list[EmojiDef] = [
    EmojiDef(emoji="❤️", title="Genuinely love this.",      section="primary"),
    EmojiDef(emoji="☕", title="I need a break. Now.",       section="primary"),
    EmojiDef(emoji="👍", title="Yes. More of this.",         section="primary"),
    EmojiDef(emoji="🔥", title="This is absolute fire.",     section="primary"),
    EmojiDef(emoji="🤔", title="Hmm... not convinced yet.",  section="primary"),
    EmojiDef(emoji="🖥️", title="I can't see your screen.",   section="signal", badge="❌"),
    EmojiDef(emoji="⚔️", title="Fight me on this.",          section="overflow"),
    EmojiDef(emoji="😂", title="I'm dead 💀",                section="overflow"),
    EmojiDef(emoji="🤯", title="My brain just exploded.",    section="overflow"),
    EmojiDef(emoji="🍕", title="Pizza time!",                section="overflow"),
    EmojiDef(emoji="💡", title="Wait, I have an idea!",      section="overflow"),
    EmojiDef(emoji="✅", title="Agreed. 100%.",              section="overflow"),
    EmojiDef(emoji="❌", title="Nope. Hard disagree.",       section="overflow"),
]

ALLOWED_EMOJI: frozenset[str] = frozenset(e.emoji for e in EMOJI_CATALOG)
```

Order = list order. `section` drives placement; `badge` is the small overlay
glyph on the "can't see your screen" button (it sends plain `🖥️`).

### 2. `daemon/emoji/router.py` (modified)

Replace the length guard with membership:

```python
emoji = body.emoji.strip()
if emoji not in ALLOWED_EMOJI:
    return JSONResponse({"error": "Emoji not allowed"}, status_code=400)
```

This is the single ingestion point, so it covers participant and host
(`__host__`) reactions alike, and rejects before anything reaches the overlay
or host WS.

### 3. `daemon/participant/router.py` (modified)

Add `emoji_catalog: list[EmojiDef]` to `ParticipantStateResponse` and include
`EMOJI_CATALOG` in the `/state` payload built in `get_participant_state`. The
list is static, so it is the same object for every participant. Regenerate the
OpenAPI snapshot afterward (the contract test asserts on it).

### 4. `static/participant.html` (modified)

- Remove the hardcoded `<button>` markup inside `#emoji-main-bar` (the five
  primary buttons + the screen button) and `#emoji-overflow` (the seven
  overflow buttons). Keep the container divs, the TV separator
  (`#emoji-tv-sep`), the plus separator (`#emoji-plus-sep`), and the `+`
  overflow wrapper (`#emoji-more-wrap`).
- Add `renderEmojiBar(catalog)`:
  - `primary` → buttons inserted before `#emoji-tv-sep`, `onclick` →
    `sendEmoji(this.textContent.trim(), this)`.
  - `signal` → button inserted between `#emoji-tv-sep` and `#emoji-plus-sep`,
    rendered with the badge overlay span, `data-emoji` carrying the plain
    emoji, `onclick` → `sendEmoji(this.dataset.emoji, this)`.
  - `overflow` → buttons inside `#emoji-overflow`, `onclick` →
    `addEmojiToBar(this)`.
  - Call it when `/state` resolves, then run `restorePromotedEmojis()` so the
    localStorage promote-to-bar state is reapplied after the dynamic render.
- Preserve `sendEmoji`, `addEmojiToBar`, `_promoteEmoji`,
  `restorePromotedEmojis`, `scheduleHideOverflow`, the onboarding CSS hook
  (`#emoji-main-bar button`), and localStorage persistence unchanged in intent.
- **No hardcoded fallback list.** If `emoji_catalog` is absent or empty the bar
  renders empty — that is the accepted cost of zero duplication.

## Data flow

1. Page loads → `GET /{sessionId}/api/participant/state` (proxied through
   Railway to the daemon).
2. Response includes `emoji_catalog`. `renderEmojiBar` builds the buttons.
3. User clicks → `sendEmoji` → `POST .../emoji/reaction`.
4. Daemon checks `emoji ∈ ALLOWED_EMOJI`; on pass forwards to overlay + host
   WS (and, in talk mode, bumps the cumulative counter).

## Error handling / edge cases

- Reaction with a non-whitelisted but short emoji (e.g. `🎉`) → `400`.
- Empty/whitespace emoji → `400` (still caught by the membership check).
- Whitespace is stripped before the membership check (matches today).
- `/state` fetch failure → empty bar, no crash, no fallback list.
- The screen button sends `🖥️` (the badge `❌` is presentation only); `🖥️` is
  in `ALLOWED_EMOJI`. `❌` is independently whitelisted via the overflow
  "Nope" button.

## Testing

- `tests/daemon/test_emoji_router.py`: switch valid-case emoji to a
  whitelisted one (`❤️`); add a case that a short non-whitelisted emoji
  (`🎉`) → `400`; keep empty → `400`.
- New `tests/daemon/test_emoji_catalog.py`: catalog non-empty; `ALLOWED_EMOJI`
  derived from catalog; screen/signal entry present with its badge; every
  `emoji` non-empty.
- Regenerate and verify the OpenAPI snapshot for the new `/state` field.
- Confirm the hermetic participant-interaction test
  (`tests/docker/test_participant_interactions.py`) still passes against the
  data-driven bar.

## Process

Implemented in a git worktree (`worktree-emoji-whitelist`) because another
Claude session is active in the same checkout.
