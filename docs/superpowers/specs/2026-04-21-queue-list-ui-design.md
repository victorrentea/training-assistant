# Queue List UI Redesign

**Date:** 2026-04-21  
**Status:** Approved

---

## Overview

Replace the Pop/Skip queue workflow with a persistent list of queued questions displayed below the backstage textarea. The host freely selects any question from the list, edits if needed, and sends it. This removes the linear auto-advance queue model in favor of manual selection.

---

## Backend Changes

### New Pydantic Model

```python
class QueuedQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]
```

### Updated PollQueueStatus

```python
class PollQueueStatus(BaseModel):
    pending: int
    items: list[QueuedQuestion]   # all queued questions, in order
    current: QueuedQuestion | None = None  # always items[0] if non-empty, kept for backward compat
```

`items` and `current` are both populated on every `GET /api/{session_id}/host/poll` response. `current` equals `items[0]` (or `None`); kept because existing callers may read it.

### New Endpoint

`DELETE /api/{session_id}/host/poll/queue/{index}`

- Removes the question at position `index` (0-based) from the queue.
- Broadcasts `PollQueueUpdatedMsg`.
- Returns 204 No Content.
- Returns 404 if index is out of range.

### PollQueue Class Simplification

The internal `_index` advance pointer and `advance()` method are removed. The queue becomes a simple list. `current()` returns `self._questions[0]` (or `None`).

Add `remove(index: int)` method:

```python
def remove(self, index: int) -> None:
    del self._questions[index]

def current(self) -> QueuedQuestion | None:
    return self._questions[0] if self._questions else None
```

Remove: `advance()`, `skip()`, and `self._index` field.

### Removed Endpoints

- `POST /api/{session_id}/host/poll/queue/submit` — deleted
- `POST /api/{session_id}/host/poll/queue/skip` — deleted

---

## Host UI Changes (`static/host.html` + `static/host.js`)

### Layout

Below the backstage textarea and button row, add a scrollable question list that fills all remaining vertical space down to the footer:

```
[ textarea ]
[ correct-count input ]  [ Send ]  [ Clear ]
─────────────────────────
• Question title A
• Question title B
• Question title C
  ...
─────────────────────────
```

The list is a `<ul id="queue-list">` with `overflow-y: auto` and `flex: 1` to fill vertical space.

### Removed Buttons

- **Pop** (`#pop-queue-btn`) — removed
- **Skip** (`#backstage-skip-btn`) — removed

### New Button

- **Clear** — clears the textarea, clears hidden JS queue state (`selectedQueueIndex`, `selectedQueueItem`), makes `#correct-count` editable again.

### Interaction: Click List Item

1. Stores `selectedQueueIndex = i` and `selectedQueueItem = items[i]` in JS.
2. Calls `initComposer(item.question + '\n\n' + item.options.join('\n'))` to populate the textarea.
3. Sets `#correct-count` value to `item.correct_indices.length`, marks it `readonly`.
4. Highlights the selected list item visually.

### Interaction: Send (Create) Button

When `selectedQueueIndex !== null`:

1. Fires the poll as normal (using textarea content + hidden `correct_indices` from `selectedQueueItem`).
2. Calls `DELETE /api/{session_id}/host/poll/queue/{selectedQueueIndex}`.
3. Clears textarea, resets `selectedQueueIndex = null`, `selectedQueueItem = null`.
4. Makes `#correct-count` editable again.

When no queue item is selected (manual entry): existing behavior unchanged.

### Interaction: Click Another List Item

Replaces the currently loaded item — `selectedQueueIndex` and textarea update to the new selection. No API call needed.

### Interaction: Clear Button

- Clears textarea (calls existing clear/reset logic).
- Sets `selectedQueueIndex = null`, `selectedQueueItem = null`.
- Makes `#correct-count` editable.

### List Rendering

`renderPollQueuePanel(queue)` updated to:
- Render `queue.items` as `<li>` elements showing `item.question` (title only).
- Attach click handlers per item.
- Re-apply highlight to `selectedQueueIndex` if still valid after refresh.

---

## Answer Visibility

Correct answers (`correct_indices`) are **never displayed** in the UI. They are:
- Stored in hidden JS state (`selectedQueueItem.correct_indices`) when a queue item is loaded.
- Passed to the poll creation call invisibly.
- The `#correct-count` input shows only the *count* (readonly when a queue item is loaded).

---

## Files Affected

| File | Change |
|---|---|
| `daemon/quiz/queue.py` | Add `remove(index)` method |
| `daemon/quiz/queue_router.py` | Add `DELETE /{index}`, remove `/submit` and `/skip` |
| `daemon/poll/router.py` | Update `PollQueueStatus` and `HostPollStateResponse` |
| `static/host.html` | Remove Pop/Skip buttons, add Clear button, add `#queue-list` |
| `static/host.js` | Update `renderPollQueuePanel`, click handlers, Send logic, Clear logic |

---

## Out of Scope

- Reordering queue items via drag-and-drop.
- Editing a queue item before sending (textarea edit is allowed but not synced back to queue).
- Persistence of the queue across daemon restarts.
