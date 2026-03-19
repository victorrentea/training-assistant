 # Q&A with Upvoting — Design Spec

**Date:** 2026-03-18
**Status:** Approved

---

## Overview

A live Q&A feature where participants submit questions and upvote others' questions during a workshop session. The host moderates the list in real time. Designed to maximize audience engagement — participants compete for upvotes and points.

---

## Core Product Goal

Increase engagement in tired, bored, or distracted audiences. Real-time points, competition, and visible social proof (upvote counts) are first-class requirements, not nice-to-haves.

---

## Navigation Model

**Tab switch = activity switch.** Clicking a tab on the host panel immediately changes `current_activity` for all participants — no separate Open/Close buttons for Q&A or Word Cloud.

- **Poll tab** → participants see current poll (or idle if none)
- **Word Cloud tab** → participants enter word cloud mode
- **Q&A tab** → participants enter Q&A mode

Each tab has only a **Clear** button to reset its content. Poll additionally has a **Launch** button to create a new poll.

`switchTab()` in `host.js` makes an API call to set the active activity:
```
POST /api/activity  { "activity": "poll" | "wordcloud" | "qa" | "none" }
```

Each activity (Poll, Word Cloud, Q&A) is **independent** — they have their own routers, state fields, and UI panels. Switching tabs does not clear or affect the other activities' content.

`POST /api/activity` **replaces** the existing `POST /api/wordcloud/status` endpoint. The word cloud router is updated to remove its own activation logic; `current_activity` is controlled exclusively through `/api/activity`.

Questions persist across tab switches — they only disappear when the host presses **Clear**.

---

## Data Model

Added to `AppState`:

```python
qa_questions: dict[str, dict]
# question_id (UUID) -> {
#   id: str,
#   text: str,
#   author: str,
#   upvoters: set[str],   # participant names who upvoted
#   answered: bool,
#   timestamp: float
# }
```

Serialization: `upvoters` (set) → list in JSON broadcast.

Upvote entries persist even if the upvoter disconnects — names are stored as strings, not live references.

---

## Participant Identity

Participants are identified by the name they chose at join time (stored in `localStorage`, sent via WebSocket). No authentication. HTTP endpoints for Q&A receive `name` in the request body — the same name the participant registered with.

**Known limitation:** The server does not verify that the `name` in the request body matches the WebSocket session. A participant could technically submit under a different name. This is accepted — the tool is used in a trusted workshop context.

---

## Scoring (real-time)

| Action | Points awarded to |
|---|---|
| Submit a question | +100 to author |
| Receive an upvote from another participant | +50 to author |

Points are awarded immediately at the moment of the action via `state.scores`. Upvoters receive no points. Marking a question as answered does not affect points.

Points are **irrevocable and one-shot**: +100 is awarded once at submit; +50 is awarded once per upvote received. Deleting a question does not revoke points already awarded.

---

## Rules

- **Upvoting:** One upvote per question per participant. Cannot upvote own question. **Upvotes are final — cannot be retracted.**
- **Submissions:** Unlimited questions per participant. Max length: 280 characters. Empty submissions rejected.
- **Answered questions:** Marked visually (strike-through, dimmed) — not deleted.
- **Merge workflow:** Host edits one question + deletes the other. No special merge function needed. Points already awarded before the delete are not revoked.

---

## Sorting

- **Always sorted by upvote count descending**, with timestamp as tiebreaker (older questions first among equal upvotes).
- On first submission (zero upvotes), questions appear in chronological order naturally via the tiebreaker.

---

## Leave Confirmation Dialog

When a participant presses the **Leave** (✕) button, a confirmation dialog appears:

> "If you leave, you will lose your points, your questions, and all upvotes. Are you sure?"

Buttons: **Cancel** (stays) / **Leave** (proceeds). This applies whenever a participant attempts to leave, regardless of active activity.

---

## Condensed Layout (Participant)

When many questions are present, cards must fit within the viewport without scrolling. Implementation: reduce card padding and font size when question count exceeds a threshold (e.g., 6+).

---

## API Endpoints

### Public (participants)
```
POST /api/qa/question           { name: "Maria", text: "..." }
POST /api/qa/upvote             { name: "Maria", question_id: "..." }
```

### Protected (host only)
```
PATCH /api/qa/question/{id}     { text: "..." }       — edit text
DELETE /api/qa/question/{id}                          — delete
POST /api/qa/answer/{id}        { answered: bool }    — toggle answered
POST /api/qa/clear                                    — delete all questions
```

### Activity switching (host only, already protected)
```
POST /api/activity              { activity: "poll" | "wordcloud" | "qa" | "none" }
```

---

## State Broadcast

Q&A state included in the existing `build_state_message()` broadcast:

```python
{
  ...existing fields...,
  "qa_questions": [
    {
      "id": "uuid",
      "text": "...",
      "author": "Maria",
      "upvote_count": 12,
      "upvoters": ["Andrei", "Ion"],   # needed client-side to disable upvote button
      "answered": false,
      "timestamp": 1234567890.0
    }
  ]
}
```

Broadcast is triggered on every Q&A mutation (submit, upvote, edit, delete, answer toggle, clear).

---

## UI — Participant

**Layout:** Input field + Send button at top. Question list below, sorted by upvotes.

**Question card:**
- Question text
- Author name
- Upvote button (▲) + count — disabled if already upvoted or own question
- Dimmed + strike-through if answered

**Condensed mode:** When 6+ questions, reduce card padding and font size to keep all visible without scroll.

---

## UI — Host

**Left column (Q&A tab):**
- Tab bar: Poll | ☁ Word Cloud | ❓ Q&A
- When Q&A tab active: just a **Clear** button at bottom

**Center column (when Q&A tab active):**
- Header: "❓ Questions — N"
- Question list sorted by upvotes, with per-question actions:
  - **✓ Answered** (toggle) — dims the card, strike-through text
  - **✕ Delete**
  - **✎ Edit** (inline or modal)
- Answered questions shown dimmed with strike-through at bottom of list

---

## Files to Create / Modify

| File | Change |
|---|---|
| `main.py` or `state.py` | Add `qa_questions` to `AppState`, `ActivityType.QA` |
| `routers/qa.py` | New router with all Q&A endpoints |
| `routers/activity.py` | New router for `POST /api/activity` (tab switch) |
| `messaging.py` | Include `qa_questions` in `build_state_message()` |
| `main.py` | Register new routers |
| `static/host.html` | Add Q&A tab, Q&A center panel |
| `static/host.js` | `switchTab()` → API call; Q&A controls + list rendering |
| `static/participant.js` | Handle `current_activity === 'qa'`; render Q&A screen; leave confirmation dialog |
| `static/participant.html` | No structural changes needed — Q&A DOM injected entirely from JS, following word cloud pattern |
| `CLAUDE.md` | Update auth scope list to include new protected endpoints |

---

## Out of Scope

- Persistent Q&A history across server restarts
- Anonymous mode (author always visible)
- Pinning questions
- Host submitting questions on behalf of participants
- Rate limiting per participant
