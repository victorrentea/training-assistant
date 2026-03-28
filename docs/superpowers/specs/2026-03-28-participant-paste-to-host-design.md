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
- **No limit** on number of sends — each send appends a new entry

## Backend

### State

New field on `AppState`:

```python
paste_texts: dict[str, list[str]]  # uuid → list of texts (append order, latest last)
```

### WebSocket Messages

**Participant → Server:**
```json
{"type": "paste_text", "text": "...up to 100KB..."}
```
- Validates text is non-empty and ≤ 100KB
- Appends to `paste_texts[uuid]`
- Triggers `broadcast_state()` so host sees the new entry

**Host → Server:**
```json
{"type": "paste_dismiss", "uuid": "participant-uuid", "index": 0}
```
- Removes the entry at the given index from `paste_texts[uuid]`
- Triggers `broadcast_state()` to update host view

### Host State Builder

Include paste texts in the host participant list. Each participant object gains:
```json
{"paste_texts": ["text1", "text2"]}
```

Only participants with non-empty paste_texts lists include this field (to keep payloads lean).

## Host Side

- Each participant row in the participant list shows **one 📋 icon per pending text**, positioned inline after the name and before the score
- Latest text is rightmost
- **Hover** on an icon shows a tooltip with the first ~100 characters of that text
- **Click** copies the full text to the host's clipboard via `navigator.clipboard.writeText()` and sends a `paste_dismiss` WebSocket message to remove that entry
- Icon fades out briefly on dismiss

## Data Flow

1. Participant opens modal → pastes text → clicks Send
2. WebSocket `paste_text` → server appends to `paste_texts[uuid]`
3. Server broadcasts updated host state (participant list includes paste_texts)
4. Host sees 📋 icon(s) appear on that participant's row
5. Host hovers → tooltip preview (first ~100 chars) → clicks → text copied to clipboard
6. WebSocket `paste_dismiss` → server removes entry → broadcast updates host view

## Out of Scope

- No scoring for sending text
- No persistence across server restart (same as all other state)
- Conference mode excluded — button hidden
- No file or image support — text only
- No participant-side history or undo
