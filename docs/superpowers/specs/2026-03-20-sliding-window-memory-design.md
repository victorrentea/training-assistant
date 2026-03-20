# Sliding Window with Long-Term Bullet Memory

**Issue:** [#27](https://github.com/victorrentea/training-assistant/issues/27)
**Date:** 2026-03-20

## Problem

After ~2 hours, the 30-minute transcript window means early topics are lost from the summary. The current prompt asks Claude to "preserve still-relevant existing bullets, update evolved ones, drop stale ones" — but Claude may aggressively prune older bullets that aren't reinforced by the current transcript window.

## Design: Locked + Draft Two-Tier Bullets

### Approach

Split the bullet list into two tiers, enforced in daemon code (not just prompt):

- **Locked bullets**: all bullets from previous cycles — sent to Claude as read-only context, preserved verbatim by code.
- **Draft bullets**: output from the most recent cycle — promoted to locked at the start of the next cycle.

Each cycle:
1. Promote current `draft_points` → append to `locked_points`
2. Call Claude with locked points as read-only context + last 30 min transcript
3. Claude returns only **new** bullets (1-7 per cycle)
4. Post `locked_points + new_draft_points` to server

### Data Model

Bullets are posted to the server as plain `{"text": "...", "source": "notes|discussion"}` — no `locked` field in the server payload. The locked/draft distinction lives only in the daemon's local state.

The server's `AppState.summary_points` stores the full concatenated list unchanged.

### Session Date Bullet

The "Session date: YYYY-MM-DD" bullet (currently injected by `generate_summary` on every call) is moved out of the summarizer. Instead, the daemon injects it once into `locked_points` at initialization. The summarizer no longer handles date bullets.

### Prompt Changes (`daemon/summarizer.py`)

The system prompt changes from "preserve/update/drop existing bullets" to generating only new bullets:

```
You are a technical workshop summarizer. You extract high-density takeaways from a live session.

Input: transcript excerpt, optionally trainer's session notes, optionally established key points from earlier in the session.

Output rules:
- Each bullet: ONE actionable or factual technical statement (max 15 words).
- Write like a cheat-sheet: name patterns, tools, trade-offs, rules-of-thumb, commands, gotchas.
- GOOD: "Extract Method refactoring reduces cyclomatic complexity per function"
- BAD: "Participants shared experiences about refactoring" (vague, no knowledge)
- Never describe what happened socially — only capture WHAT was taught or concluded.
- Output 1-7 NEW bullets covering genuinely new takeaways not already in the established list.
- Do NOT repeat, rephrase, or contradict established key points — they are already captured.
- Ignore transcription noise, filler, off-topic chatter.
- For each bullet, indicate source:
  - "notes" if from SESSION NOTES (trainer's agenda/material)
  - "discussion" if from TRANSCRIPT (what was actually said)

Return ONLY a JSON array of objects. No markdown, no explanation.
Example: [{"text": "Outbox pattern decouples DB writes from message publishing", "source": "discussion"}]
```

Locked bullets are sent in the user message as:
```
ESTABLISHED KEY POINTS (read-only reference — do NOT repeat or rephrase these):
[...locked bullets text list...]
```

**First cycle edge case**: no locked points exist yet — prompt omits the "ESTABLISHED" section. Initial output (up to 7 bullets) becomes the first draft.

### Function Signature Change

`generate_summary(config, existing_points)` becomes `generate_summary(config, locked_points)` — it receives only the locked (read-only) context and returns only new bullets.

The function retains its JSON parsing, normalization, and error handling logic internally.

### Daemon State (`quiz_daemon.py`)

Two new local lists maintained across cycles:
- `locked_points: list[dict]` — grows monotonically, initialized with the session date bullet
- `draft_points: list[dict]` — replaced each cycle

**Daemon restart**: both lists reset to empty (same as current behavior — no regression). The daemon could fetch existing points from the server on startup to seed `locked_points`, but this is out of scope for now.

**Force-summary**: follows the same locked/draft promotion cycle as periodic summaries (shared code path).

### Bullet Count Growth

With 1-7 new bullets per 5-minute cycle, a 2-hour session (24 cycles) could produce up to 168 bullets in the worst case. In practice, many cycles will produce 0-2 bullets (quiet periods, exercises). Acceptable for now — consolidation can be added later if needed.

### Files Changed

| File | Change |
|---|---|
| `daemon/summarizer.py` | New prompt, function takes `locked_points`, returns only new bullets, remove date bullet injection |
| `quiz_daemon.py` | Maintain locked/draft lists, promote draft→locked each cycle, inject date bullet at init, concatenate before posting |

### No Backend or Frontend Changes

- `AppState.summary_points` stores the full list as before
- Frontend renders a flat bullet list as before

## Acceptance Criteria

- Bullets from the first 30 min of a 2-hour session are still present in the summary at the end
- The prompt distinguishes established key points (preserved in code) from new discussion (generated by Claude)
- Total bullet count stays manageable (1-7 new per cycle, locked bullets accumulate)
