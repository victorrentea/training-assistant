# LOTR Avatars for Participants — Design Spec

## Summary

Assign each participant a small LOTR-themed chibi/cartoon avatar displayed everywhere their name appears. Avatars add visual identity and fun to the workshop experience.

Closes open questions from issue #12: no re-roll, avatars are fixed per UUID for the session.

## Avatar Assets

- 30 AI-generated chibi/cartoon style portraits, one per LOTR name in `LOTR_NAMES`
- Stored as `static/avatars/{name_slug}.png` (e.g., `gandalf.png`, `tom-bombadil.png`)
- Slug rule: `name.lower().replace(' ', '-')` — e.g., "Tom Bombadil" → `tom-bombadil.png`, "The One Ring" → `the-one-ring.png`, "Grima Wormtongue" → `grima-wormtongue.png`
- Source size: 64x64px PNG, displayed at 32px in the UI
- Committed directly to the repo (tiny files)
- Note: "The One Ring" and "Shadowfax" are not characters with faces — their chibi portraits will be stylized objects/animals rather than humanoid portraits

## Assignment Logic

- **Assign once per UUID**: avatar is assigned on the **first** `set_name` for a UUID. Subsequent renames do NOT change the avatar. This ensures visual stability.
- **LOTR names**: if the first name is a LOTR name, participant gets the matching character avatar (Gandalf → `gandalf.png`)
- **Custom/Guest names**: deterministic pick from the pool using `int(uuid.replace('-', ''), 16) % len(LOTR_NAMES)` (UUID parsed as hex integer — deterministic across restarts, unlike Python's `hash()`)
- **Persistence**: avatar stored in `state.participant_avatars`, survives reconnects within the same server session. State resets on server restart (consistent with all other state per CLAUDE.md).
- **No re-roll**: participants cannot change their avatar

## Server Changes

### State (`state.py`)
- Add `participant_avatars: dict[str, str]` — UUID → avatar filename (preserved on disconnect, like `participant_names`)
- Add helper function `get_avatar_filename(name: str) -> str` — returns slug-based filename for a LOTR name
- Add helper function `assign_avatar(uuid: str, name: str) -> str` that:
  1. If UUID already has an avatar in `participant_avatars`, return it (assign-once rule)
  2. If name is in `LOTR_NAMES`, return the matching avatar filename
  3. Otherwise, pick deterministically: `LOTR_NAMES[int(uuid.replace('-', ''), 16) % len(LOTR_NAMES)]`'s avatar filename

### WebSocket (`routers/ws.py`)
- On `set_name`, call `assign_avatar(uuid, name)` and store in `state.participant_avatars[uuid]`
- Include avatar filename in state broadcasts
- On disconnect: do NOT clean up `participant_avatars` (preserve like `participant_names`)

### Messaging (`messaging.py`)
- Add `my_avatar` field to participant state message (in `build_participant_state()`, parallel to `my_score`)
- Add `avatar` field to each entry in the host `participants` list (in `broadcast_participant_update()`)
- Add `author_avatar` field to Q&A question objects in both `_build_qa_for_participant()` and `_build_qa_for_host()`

## Frontend Changes

### Participant UI (`participant.html`, `participant.js`, `participant.css`)
- **Top bar**: show avatar between microphone icon and name — `<img src="/static/avatars/{file}" class="avatar">`
- **Q&A**: show avatar next to question author name
- Read `my_avatar` from state messages to display own avatar in top bar

### Host UI (`host.html`, `host.js`, `host.css`)
- **Participant list**: show avatar before each name
- **Q&A**: show avatar next to question author name

### Shared CSS (`common.css`)
- Add `.avatar` class: `width:32px; height:32px; border-radius:50%; object-fit:cover; vertical-align:middle;`
- Add `.avatar-fallback` for error case: colored circle with centered initial letter

## Data Flow

1. Participant connects via WebSocket with UUID
2. Participant sends `set_name` message
3. Server calls `assign_avatar(uuid, name)` — returns existing avatar if already assigned, or computes and stores new one
4. Server broadcasts state including `my_avatar` (to participant) and `avatar` per participant (to host)
5. All clients render avatar `<img>` next to names

## Fallback

If the avatar image fails to load (`onerror`), display a colored circle with the first letter of the participant's name. Color derived from `int(uuid.replace('-', ''), 16)` for consistency.

## Out of Scope

- Avatar re-roll / selection UI
- Animated avatars
- Custom avatar upload
- Avatar in word cloud visualization (words are text-only)
- Startup validation of avatar files (fallback handles missing images gracefully)

## Post-Implementation

- Update `AppState` model documentation in CLAUDE.md to include `participant_avatars`
