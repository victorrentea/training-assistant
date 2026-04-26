# Poll Re-scoring on Host Correct-Answer Change

**Date:** 2026-04-26
**Status:** Approved for implementation

## Problem

When the host marks an option as correct in a poll, points flow to participants who voted for that option. Today, if the host then marks a *different* option as correct, the UI shows the new correct answer — but **scores remain frozen from the first reveal**. A participant who originally guessed right keeps their points; a participant whose vote now matches the corrected answer earns nothing.

`daemon/poll/state.py` currently enforces this with an `already_revealed` guard around the score-awarding loop in `reveal_correct`.

## Goal

Make `reveal_correct` idempotent with respect to scoring: each call must reflect the *current* correct answer set.

- A participant whose vote no longer matches → their poll-awarded points are removed.
- A participant whose vote now matches → they receive points (using the same speed-decay + partial-credit algorithm as today).
- The host can re-mark the correct answer any number of times; scores always reflect the latest call.

## Non-Goals

- No change to the speed-bonus algorithm. The "fastest correct voter" baseline is re-anchored on each call (decision: brainstorming option A).
- No change to multi-select partial-credit math.
- No change to participant UI — `ScoresUpdatedMsg` is already broadcast and clients re-render scores live.
- No tracking of historical "what was awarded on reveal #N" beyond the most recent call.

## Design

### State change

Add a single field to `PollState` (in `daemon/poll/state.py`):

```python
self.awarded_points: dict[str, int] = {}   # pid → points awarded by the most recent reveal
```

Reset it in `__init__`, `clear()`, and `create_poll()` alongside the other per-poll fields.

### Algorithm change in `reveal_correct`

Before the existing scoring loop, reverse the previous awards:

```python
for pid, prev_pts in self.awarded_points.items():
    scores_obj.add_score(pid, -prev_pts)
self.awarded_points = {}
```

Inside the existing scoring loop, replace:

```python
if pts > 0 and not already_revealed:
    scores_obj.add_score(pid, pts)
```

with:

```python
if pts > 0:
    scores_obj.add_score(pid, pts)
    self.awarded_points[pid] = pts
```

Drop the `already_revealed` local — no longer used.

### Persistence

The daemon writes a session snapshot to disk on each state change (see `_runtime_snapshot()` in `daemon/__main__.py` ≈ lines 216-224). For consistency with the existing `correct_indices`, `votes`, etc., we add `awarded_points` to both the model and the snapshot writer:

1. `PersistedPollState` (in `daemon/persisted_models.py`) gains:

   ```python
   awarded_points: dict[str, int] = Field(
       default_factory=dict,
       description="participant_uuid → points awarded by most recent reveal_correct (for delta on next call)",
   )
   ```

2. In `daemon/__main__.py` snapshot writer, add:

   ```python
   "awarded_points": dict(poll_state.awarded_points),
   ```

   alongside the other poll fields.

**Note on restore:** Poll state is not currently rehydrated from snapshot on daemon restart (`_apply_runtime_snapshot_restore` calls `sync_from_restore` for participant/wordcloud/qa/misc/codereview/debate but **not** poll). This feature does not change that; we simply match the existing snapshot-write pattern so `awarded_points` is in the JSON if and when poll restore is wired up.

### Broadcast

No new WS messages. The existing `PollCorrectRevealedMsg` (correct indices) and `ScoresUpdatedMsg` (full snapshot) already cover both effects: participants see the new correct answer and their updated score.

## Edge Cases

| Case | Behavior |
|---|---|
| Host calls `reveal_correct` once | Identical to today — `awarded_points` was empty, so no reversal happens. |
| Host calls `reveal_correct` 3+ times | Each call reverses the previous award and applies fresh — always correct. |
| Host marks "no options correct" (empty list) | Previous awards reversed; no new awards. Score returns to pre-reveal baseline. |
| Multi-select with partial credit | Same per-pid arithmetic — `awarded_points[pid]` stores the partial-credit amount that was applied. |
| Vote was zero-points (wrong answer) and stays wrong | Not stored in `awarded_points` (we only store `pts > 0`). No-op on reversal. |

## Tests

### BDD scenario (`tests/docker/features/poll.feature`)

```gherkin
@seq
Scenario: Host changes the correct option, points re-flow
  Given a participant "Alice" selects "Java"
  And   a participant "Bob" selects "Python"
  And   the host closes the poll
  And   the host marks "Java" as correct option
  And   Alice is awarded 1000 points
  And   Bob is awarded 0 points
  When  the host marks "Python" as correct option
  Then  Alice is awarded 0 points
  And   Bob is awarded 1000 points
```

### Daemon unit tests (`tests/daemon/test_poll_state.py`)

Three new tests, all exercising `reveal_correct` called twice on the same poll:

1. **Single-select:** first reveal awards Alice 1000, second reveal (different option) awards Bob 1000 and zeroes Alice.
2. **Multi-select with partial credit:** verify the partial-credit amount is correctly subtracted on the second reveal.
3. **Empty correct set on second reveal:** verify all previous awards are reversed and no new awards are made.

A fourth test asserts `awarded_points` is reset by `create_poll` and `clear()`.

## What's Explicitly NOT Changing

- `daemon/scores.py` — `add_score` already supports negative deltas.
- Participant page JS — already re-renders on `ScoresUpdatedMsg`.
- Host poll tab — already re-fetches state on `PollCorrectRevealedMsg`.
- The route `PUT /api/{session_id}/host/poll/correct` and its `RevealCorrectRequest` body are unchanged.

## Files Touched

| File | Change |
|---|---|
| `daemon/poll/state.py` | Add `awarded_points`; reverse-then-apply in `reveal_correct`; drop `already_revealed`. |
| `daemon/persisted_models.py` | Add `awarded_points` field to `PersistedPollState`. |
| `daemon/__main__.py` | Add `awarded_points` to the poll dict in `_runtime_snapshot()` (≈ line 216-224). |
| `tests/daemon/test_poll_state.py` | 4 new unit tests. |
| `tests/docker/features/poll.feature` | 1 new BDD scenario (`@seq`). |
| `tests/docker/features/steps/poll_steps.py` (if needed) | Reuse existing step defs — no new glue expected. |
