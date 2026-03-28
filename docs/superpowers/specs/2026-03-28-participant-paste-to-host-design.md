# Participant Paste-to-Host

**Date:** 2026-03-28
**Status:** Approved

## Goal

Allow participants to send text snippets (up to 100KB) to the host during a workshop session. The host can then copy these texts from the participant list with a single click.

## Participant Side (workshop mode only)

- **Floating 📋 button** in bottom-right corner of the main pane, same size as emoji buttons (44×44px), positioned independently from the emoji bar, floating over content/PDF
- Hidden in conference mode
- **Click opens a modal overlay**: contains a textarea where the participant can paste text, plus a "Send" button (disabled when textarea is empty/whitespace-only per existing convention)
- **On send**: text is sent via WebSocket as a `paste_text` message, modal closes automatically, a brief "Sent!" toast appears and fades after ~1.5 seconds
- Max **10 pending texts** per participant (oldest rejected if limit reached)

## Backend

### State

New field on `AppState`:

```python
paste_texts: dict[str, list[dict]]  # uuid → [{id: int, text: str}, ...]
```

Auto-incrementing counter (`paste_next_id: int`) for unique paste IDs.

Include in `AppState.reset()` initialization. Excluded from snapshot/restore (ephemeral — not worth persisting large blobs).

### WebSocket Messages

**Participant → Server** (handled in `features/ws/router.py`):
```json
{"type": "paste_text", "text": "...up to 100KB..."}
```
- Validates text is non-empty and ≤ 100KB
- Rejects if participant already has 10 pending texts
- Appends `{id: <next_id>, text: text}` to `paste_texts[uuid]`
- Triggers `broadcast_participant_update()` (host-only — participants don't need this data)

**Host → Server:**
```json
{"type": "paste_dismiss", "uuid": "participant-uuid", "paste_id": 42}
```
- Removes the entry with matching `paste_id` from `paste_texts[uuid]` (ID-based, not index-based, to avoid race conditions)
- Triggers `broadcast_participant_update()`

### Host Participant List

Paste texts are added directly to `_build_host_participants_list()` in `core/state_builder.py` (no separate feature state builder needed). Each participant object gains:
```json
{"paste_texts": [{"id": 1, "text": "full text..."}, {"id": 2, "text": "..."}]}
```

Only included when non-empty (to keep payloads lean).

## Host Side

- Each participant row in the participant list shows **one 📋 icon per pending text**, positioned inline after the name and before the score
- Latest text is rightmost
- **Hover** on an icon shows a tooltip with the first ~100 characters of that text
- **Click** copies the full text to the host's clipboard via `navigator.clipboard.writeText()` and sends a `paste_dismiss` WebSocket message (with the paste's `id`) to remove that entry
- Icon fades out briefly on dismiss

## Data Flow

1. Participant opens modal → pastes text → clicks Send
2. WebSocket `paste_text` → server appends `{id, text}` to `paste_texts[uuid]`
3. Server calls `broadcast_participant_update()` → host receives updated participant list
4. Host sees 📋 icon(s) appear on that participant's row
5. Host hovers → tooltip preview (first ~100 chars) → clicks → text copied to clipboard
6. WebSocket `paste_dismiss` with `paste_id` → server removes entry by ID → broadcast updates host view

## Out of Scope

- No scoring for sending text
- No persistence across server restart (same as all other state)
- Conference mode excluded — button hidden
- No file or image support — text only
- No participant-side history or undo
