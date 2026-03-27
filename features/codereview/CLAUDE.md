# Code Review

## Purpose
Host pastes a code snippet; participants flag the lines they think are problematic; host reveals correct lines one by one, awarding points and sparking discussion. Optionally uses Claude Haiku to extract clean code from LLM output ("smart paste").

## Endpoints
- `POST /api/codereview` — create a code review session (snippet + optional language + smart_paste flag)
- `PUT /api/codereview/status` — close selection phase (`open: false` → phase becomes "reviewing")
- `PUT /api/codereview/confirm-line` — host confirms a line as a problem; awards 200 pts to all who flagged it
- `DELETE /api/codereview` — end code review and reset to NONE activity

## WebSocket Messages
- `codereview_select` (participant → server) → flag a line number as problematic (phase must be "selecting")
- `codereview_deselect` (participant → server) → unflag a previously selected line

## State Fields
Fields in `AppState` owned by this feature:
- `codereview_snippet: str | None` — the raw code text
- `codereview_language: str | None` — detected or host-specified language identifier
- `codereview_phase: str` — `"idle"` | `"selecting"` | `"reviewing"`
- `codereview_selections: dict[str, set[int]]` — uuid → set of flagged line numbers
- `codereview_confirmed: set[int]` — line numbers confirmed by host as problematic

## Design Decisions
- Max 50 lines per snippet.
- Smart paste calls Claude Haiku synchronously in a thread (5s timeout) to extract clean code from LLM-generated text with explanations.
- Language auto-detection is skipped if host explicitly sets a language.
- Cannot start code review if another activity is active (returns 409).
- Points are awarded at confirm time: 200 pts per confirmed line to all participants who selected it.
- `codereview_confirmed` is a Python `set`; serialized to sorted list for JSON.
