# Quiz Index-Based Voting API — Design Spec

**Date:** 2026-04-19  
**Status:** Approved

---

## Overview

Remove the concept of per-option string IDs from the quiz API. Options are identified solely by their 0-based position. This simplifies the participant API, eliminates artificial ID scaffolding (e.g. "A", "B"), and makes `vote_counts` a naturally ordered list.

---

## Motivation

Option IDs (e.g. `"A"`, `"B"`, short hex) were artificial — options are an ordered list and position is their natural identity. Removing IDs:
- Simplifies what participants receive and send
- Eliminates translation/validation of arbitrary string IDs
- Makes `vote_counts` a position-ordered list, easier to render

---

## Contract Changes

### `quiz_opened` WS (participant + host)

**Before:**
```
quiz.options: list[QuizOption{id: string, text: string}]
```
**After:**
```
quiz.options: list[string]
```

### `POST /api/participant/quiz/vote`

**Before:**
```json
{ "option_ids": ["A", "C"] }
```
**After:**
```json
{ "options": [0, 2] }
```
Field renamed to `options`, values are 0-based integer indices. Validation: indices must be in-bounds, no duplicates, count constraints apply as before.

### `quiz_closed` WS (participant + host)

**Before:**
```
vote_counts: dict[str, int]   # keyed by option id, e.g. {"A": 3, "B": 1}
total_votes: int
```
**After:**
```
vote_counts: list[int]        # indexed by option position, e.g. [3, 1, 0]
```
`total_votes` removed — derivable as `sum(vote_counts)`.  
Participants use `vote_counts` to render the voting distribution after the quiz closes.

### `quiz_correct_revealed` WS (participant + host)

**Before:**
```
correct_ids: list[string]
```
**After:**
```
correct_indices: list[int]
```

### `PUT /api/{session_id}/host/quiz/correct` (RevealCorrectRequest)

**Before:**
```json
{ "correct_ids": ["A", "C"] }
```
**After:**
```json
{ "correct_indices": [0, 2] }
```

### `POST /api/{session_id}/host/quiz` (CreateQuizRequest)

**Before:**
```json
{ "question": "...", "options": [{"id": "A", "text": "..."}, ...], "multi": false }
```
**After:**
```json
{ "question": "...", "options": ["...", "..."], "multi": false }
```
`options` is now `list[str]`. The `normalize_options` validator is simplified to only handle string items. `QuizOptionRequest` model is removed.

### `POST /api/{session_id}/host/quiz-queue` (SubmitQuestionsRequest)

**Before:**
```json
{ "questions": [{ "question": "...", "options": [{"id": "A", "text": "..."}], "correct_ids": ["A"] }] }
```
**After:**
```json
{ "questions": [{ "question": "...", "options": ["..."], "correct_indices": [0] }] }
```
`QuizQueueOption` model removed. `QuizQueueQuestion.options` becomes `list[str]`, `correct_ids` renamed to `correct_indices: list[int]`.

### `GET /api/{session_id}/host/quiz-queue` (QuizQueueStatusResponse)

`current.options` becomes `list[str]`, `current.correct_indices: list[int]`.

### Participant State (`GET /api/participant/state`)

| Before | After |
|---|---|
| `my_voted_ids: list[str]` | `my_voted_indices: list[int]` |
| `quiz_correct_ids: list[str]` | `quiz_correct_indices: list[int]` |
| `vote_counts: dict[str, int]` | `vote_counts: list[int]` |

---

## Internal State Changes (`QuizState`)

- `quiz["options"]` stores `list[str]` (plain text strings, no id wrapper).
- `votes` dict: `{uuid: {"option_indices": list[int], "voted_at": str}}`.
- `vote_counts()` returns `list[int]` of length `len(options)`, each entry = count for that position.
- `cast_vote(option_indices: list[int])`: validates all indices are in `range(len(options))`, no duplicates, count cap for multi quizzes.
- `reveal_correct(correct_indices: list[int])`: uses positions directly. Scoring logic unchanged — correct/wrong sets use indices instead of IDs.
- `_append_to_quiz_md(correct_indices)`: renders `options[i]` by position.

---

## Files to Change

| File | Change |
|---|---|
| `daemon/quiz/state.py` | Full index-based rewrite of votes, vote_counts, cast_vote, reveal_correct, _append_to_quiz_md |
| `daemon/quiz/router.py` | VoteRequest, RevealCorrectRequest, CreateQuizRequest, QuizOptionRequest removed, QuizResponse updated |
| `daemon/quiz_queue/router.py` | QuizQueueOption removed, QuizQueueQuestion.options→list[str], correct_ids→correct_indices:list[int]; fire_current() updated |
| `daemon/ws_messages.py` | QuizClosedMsg (remove total_votes, list vote_counts), QuizCorrectRevealedMsg (correct_indices), QuizOpenedMsg quiz field type |
| `daemon/participant/router.py` | State snapshot: my_voted_indices, quiz_correct_indices, vote_counts as list |
| `docs/participant-ws.yaml` | Quiz schema, quiz_closed, quiz_correct_revealed |
| `docs/host-ws.yaml` | Same as participant-ws.yaml |
| `docs/openapi.yaml` | VoteRequest, RevealCorrectRequest, CreateQuizRequest, remove QuizOption schema |
| `static/participant.html` | castVote uses index, rendering uses list[str] options, vote_counts by index, correct_indices |
| `static/host.js` | correctOptIds as Set<int>, toggleCorrect(idx), voteCounts[idx], correct_indices in reveal call, render by index |
| `daemon/persisted_models.py` | correct_ids→correct_indices:list[int], quiz_correct_ids→quiz_correct_indices:list[int]; remove legacy migration for old id-based format |
| `tests/daemon/test_quiz_router.py` | Update payloads to index-based |
| `tests/daemon/test_quiz_state.py` | Update cast_vote/reveal_correct calls |
| `API.md` | Regenerate via script |

---

## Out of Scope

- No change to scoring algorithm — only the input type changes (indices instead of IDs).
