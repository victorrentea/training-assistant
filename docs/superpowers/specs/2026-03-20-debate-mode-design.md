# "Whose Side Are You On?" — Debate Mode

## Summary

A new activity type (`ActivityType.DEBATE`) that splits participants into two camps (FOR / AGAINST a statement) and guides them through a structured debate flow. Participants first choose sides, then build arguments collaboratively, get AI-augmented cleanup, and finally have champions debate live.

**Goal:** Force participants to articulate trade-off arguments — powerful for architectural discussions in workshops.

**Activity integration:** Launching a debate sets `current_activity = ActivityType.DEBATE` and clears any previous debate state. Only one activity can be active at a time — launching a debate while a poll/Q&A/wordcloud is active replaces it (same pattern as existing activities). Launching a new debate replaces any existing debate.

---

## Phase Flow

Host advances all phases manually via "Next Phase" button. No timers.

```
Launch Debate (host types statement)
  → Phase 1: Side Selection
  → Phase 2: Arguments
  → Phase 3: AI Cleanup & Augmentation
  → Phase 4: Preparation (optional breakout rooms)
  → Phase 5: Live Debate
  → End Debate
```

---

## Phase 1 — Side Selection

- Participants see the statement and two buttons: **FOR** / **AGAINST**
- All participants can pick freely while selection is open
- Host clicks "Close Selection" → remaining participants who haven't picked are auto-assigned to balance the two sides equally (if odd remainder, the extra one goes to the smaller side; if equal, random)
- Close-selection and phase advance to `arguments` are **atomic** — one action
- Participant sees confirmation of their assigned side
- Host sees live counter of FOR / AGAINST choices

**WebSocket:** `{type: "debate_pick_side", side: "for"|"against"}`

---

## Phase 2 — Arguments

- Dual-column layout on all screens: **LEFT = AGAINST**, **RIGHT = FOR**
- Participants can only submit arguments for their own side
- Side is **inferred server-side** from `debate_sides[uuid]` — never sent by the client
- Each argument appears in real-time in the correct column for everyone
- Click on any argument to upvote it (simple counter, one upvote per participant per argument)
- **Cross-side upvoting is allowed** — a FOR participant can upvote an AGAINST argument
- Host sees both columns with all arguments
- Argument IDs generated with `uuid4()` (same pattern as Q&A question IDs)
- **Max argument length: 280 characters** (same as Q&A)

**WebSocket messages:**
- `{type: "debate_argument", text: "..."}`
- `{type: "debate_upvote", argument_id: "..."}`

---

## Phase 3 — AI Cleanup & Augmentation

Entering this phase shows all arguments read-only. Host clicks **"Run AI"** button to trigger cleanup (separate action from phase entry). The AI:

1. **Deduplicates** — merges similar arguments, marks originals with "✨ duplicate, merged above"
2. **Cleans** — fixes typos, makes text concise, preserves the author's intent
3. **Augments** — adds missing arguments marked with ✨ and "AI" as author

AI suggestions use the same styling as human arguments (same border, same background). Only difference: ✨ icon and "AI" as author name.

When arguments are merged, upvote counts are **combined** on the surviving argument. Original authors keep their submission points.

**AI Prompt input:** statement + all arguments grouped by side
**AI Prompt output:** JSON with cleaned arguments + new suggestions + merge mappings

---

## Phase 4 — Preparation

There is no backend distinction between "breakout" and "thinking pause" — the app always shows the same screen (arguments + hints + champion button). Whether the host creates external breakout rooms is their choice outside the app.

On-screen content:
- All arguments from both sides (cleaned)
- **Debate rules** (static text baked into frontend): brief rules like "Present your strongest argument first", "Address the opposing argument directly", "Give specific examples"
- **Attack/defense hints** (static text): e.g., "In what context does this trade-off matter most?", "What's the strongest counterargument?"

The **"Volunteer as Champion"** button is active. First participant to click becomes their team's champion (first-come). Both teams need a champion before the host can advance.

**WebSocket:** `{type: "debate_volunteer"}`

---

## Phase 5 — Live Debate

- Champions' names displayed prominently
- Key arguments from both sides visible as reference
- Debate rules and hints remain on screen
- Host manages speaking turns manually (voice/video in Zoom/Teams)
- Host clicks "End Debate" to finish → phase transitions to `ended`, scores are finalized

Champions debate live: each presents their side, then right of reply.

---

## State Structure

New fields on `AppState`:

```python
debate_statement: str | None
debate_phase: str | None          # "side_selection" | "arguments" | "ai_cleanup" | "prep" | "live_debate" | "ended"
debate_sides: dict[str, str]      # uuid → "for" | "against"
debate_arguments: list[dict]      # [{id, author_uuid, side, text, upvoters: set, ai_generated: bool, merged_into: str|None}]
debate_champions: dict[str, str]  # "for" → uuid, "against" → uuid
```

**Reconnection:** `debate_sides` is keyed by UUID and persists across disconnects (same as `participant_names` and `scores`). A reconnecting participant keeps their assigned side.

---

## REST API Endpoints

All protected with HTTP Basic Auth (host-only):

| Endpoint | Method | Body | Effect |
|---|---|---|---|
| `/api/debate` | POST | `{statement}` | Launch debate (resets all debate state), phase → side_selection |
| `/api/debate/close-selection` | POST | — | Auto-assign remaining + phase → arguments (atomic) |
| `/api/debate/phase` | POST | `{phase}` | Advance to next phase (including `ended` to finish) |
| `/api/debate/ai-cleanup` | POST | — | Trigger AI cleanup + augmentation (within ai_cleanup phase) |

---

## Scoring

| Action | Points |
|---|---|
| Submit argument | +100 |
| Receive upvote on your argument | +50 |
| Give an upvote | +25 |
| Volunteer as champion | +2500 |

Same weighting as Q&A for upvotes. Champion reward is deliberately large to incentivize social courage.

---

## UI Layout

### Participant

| Phase | Display |
|---|---|
| Side Selection | Statement + two large buttons (FOR / AGAINST) |
| Arguments | Dual-column (left=AGAINST, right=FOR) + text input for own side + upvote on click |
| AI Cleanup | Read-only dual-column with cleaned + ✨ AI arguments |
| Prep | All arguments + hints + debate rules + "Volunteer as Champion" button |
| Live Debate | Champions displayed + key arguments + hints |

### Host

| Phase | Display |
|---|---|
| Side Selection | Statement + live FOR/AGAINST counters + "Close Selection" button |
| Arguments | Full dual-column (both sides) + "Next Phase" button |
| AI Cleanup | "Run AI" button → results → "Next Phase" button |
| Prep | All arguments + champions + "Start Debate" button |
| Live Debate | Rules + arguments + "End Debate" button |

---

## Sequence Diagram

Full sequence diagram available at: `adoc/seq_debate_flow.puml`
