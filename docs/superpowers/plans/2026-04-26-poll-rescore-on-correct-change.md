# Poll Re-scoring on Host Correct-Answer Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `daemon/poll/state.py::PollState.reveal_correct` idempotent w.r.t. scoring, so that when the host changes which option is "correct", points are reversed from participants whose vote no longer matches and re-awarded to participants whose vote now matches.

**Architecture:** Track per-poll `awarded_points: dict[pid, int]` on `PollState`. On every `reveal_correct` call: (1) subtract previous awards from `scores`, (2) clear the dict, (3) run the existing scoring loop and record new awards into the dict. The `already_revealed` guard is removed. The field is added to the persisted snapshot (`PersistedPollState`) and to the snapshot writer in `daemon/__main__.py` for consistency with the existing poll fields.

**Tech Stack:** Python 3 · FastAPI · Pydantic · pytest · pytest-bdd · Playwright (Docker hermetic).

**Spec:** `docs/superpowers/specs/2026-04-26-poll-rescore-on-correct-change-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `daemon/poll/state.py` | Poll lifecycle + scoring algorithm | Add `awarded_points`; reverse-then-apply in `reveal_correct`; drop `already_revealed`. |
| `daemon/persisted_models.py` | Pydantic snapshot models | Add `awarded_points` field to `PersistedPollState`. |
| `daemon/__main__.py` | Daemon entrypoint + snapshot writer | Add `awarded_points` to the `poll` dict in `_runtime_snapshot()` (≈ lines 216-224). |
| `tests/daemon/test_poll_state.py` | PollState unit tests | 4 new tests. |
| `tests/docker/features/poll.feature` | BDD scenarios | 1 new `@seq` scenario. |
| `tests/docker/step_defs/test_poll.py` | BDD step glue | **No changes expected.** All step definitions already exist (named-pax `is awarded N points`, `the host marks "X" as correct option`, etc.). |

---

## Task 1: Add `awarded_points` field to `PollState` (and reset hooks)

Introduce the new field, ensure it is reset alongside the other per-poll state in `__init__`, `clear()`, and `create_poll()`. No behavior change yet — `reveal_correct` does not touch the field in this task.

**Files:**
- Modify: `daemon/poll/state.py:9-19, 21-38, 151-160`
- Test:   `tests/daemon/test_poll_state.py` (append at end)

- [ ] **Step 1: Write the failing test**

Append to `tests/daemon/test_poll_state.py`:

```python
def test_awarded_points_initialized_empty():
    ps = PollState()
    assert ps.awarded_points == {}


def test_awarded_points_reset_by_create_poll():
    ps = PollState()
    ps.awarded_points = {"alice": 1000, "bob": 500}
    ps.create_poll("Q?", ["A", "B"])
    assert ps.awarded_points == {}


def test_awarded_points_reset_by_clear():
    ps = PollState()
    ps.awarded_points = {"alice": 1000}
    ps.clear()
    assert ps.awarded_points == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py::test_awarded_points_initialized_empty tests/daemon/test_poll_state.py::test_awarded_points_reset_by_create_poll tests/daemon/test_poll_state.py::test_awarded_points_reset_by_clear -v --confcutdir=tests/daemon`
Expected: 3 FAIL with `AttributeError: 'PollState' object has no attribute 'awarded_points'`.

- [ ] **Step 3: Add the field to `__init__`**

In `daemon/poll/state.py`, locate `class PollState: def __init__(self):` (around line 9). After the line `self._vote_counts_cache: list[int] | None = None` add:

```python
        self.awarded_points: dict[str, int] = {}  # pid → points awarded by most recent reveal_correct
```

The full `__init__` block then ends:

```python
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: list[int] | None = None
        self.awarded_points: dict[str, int] = {}  # pid → points awarded by most recent reveal_correct
```

- [ ] **Step 4: Reset in `create_poll`**

In the same file, in `create_poll(...)` method (around line 21-38), after the existing `self._vote_counts_dirty = True` line, add:

```python
        self.awarded_points = {}
```

The bottom of the method should now read:

```python
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        self.awarded_points = {}
        return dict(self.poll)
```

- [ ] **Step 5: Reset in `clear`**

In `clear(self) -> None:` (around line 151-160), after `self._vote_counts_cache = None` add:

```python
        self.awarded_points = {}
```

The full method should read:

```python
    def clear(self) -> None:
        self.poll = None
        self.poll_active = False
        self.votes.clear()
        self.poll_opened_at = None
        self.poll_correct_indices = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        self._vote_counts_cache = None
        self.awarded_points = {}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py -v --confcutdir=tests/daemon`
Expected: All tests PASS (the 3 new + the existing ones — none of which should regress because `awarded_points` is unused so far).

- [ ] **Step 7: Commit**

```bash
git add daemon/poll/state.py tests/daemon/test_poll_state.py
git commit -m "feat(poll): add awarded_points field to PollState

No behavior change yet — field is initialized empty and reset by
create_poll() and clear(), preparing for reveal_correct to use it
in the next commit."
```

---

## Task 2: Reverse-and-reapply scoring in `reveal_correct`

Make `reveal_correct` idempotent: subtract previously-awarded points before computing new ones, and record the new awards in `awarded_points`. Drop the `already_revealed` guard.

**Files:**
- Modify: `daemon/poll/state.py:78-141` (specifically the `already_revealed` line and the `if pts > 0 and not already_revealed` block)
- Test:   `tests/daemon/test_poll_state.py` (append at end)

- [ ] **Step 1: Write the failing test for single-select re-reveal**

Append to `tests/daemon/test_poll_state.py`:

```python
def test_reveal_correct_twice_single_select_moves_points():
    """Second reveal with a different option must zero the first voter and award the new one."""
    ps = PollState()
    ps.create_poll("Q?", ["A", "B", "C"])
    ps.open_poll(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    ps.votes = {
        "alice": {"option_indices": [0], "voted_at": vote_time},   # voted A
        "bob":   {"option_indices": [1], "voted_at": vote_time},   # voted B
    }
    scores = MockScores()

    # First reveal: A is correct → Alice gets 1000, Bob gets 0.
    ps.reveal_correct([0], scores)
    assert scores.scores.get("alice") == _MAX_POINTS
    assert scores.scores.get("bob", 0) == 0
    assert ps.awarded_points == {"alice": _MAX_POINTS}

    # Second reveal: B is correct → Alice goes back to 0, Bob gets 1000.
    ps.reveal_correct([1], scores)
    assert scores.scores.get("alice", 0) == 0
    assert scores.scores.get("bob") == _MAX_POINTS
    assert ps.awarded_points == {"bob": _MAX_POINTS}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py::test_reveal_correct_twice_single_select_moves_points -v --confcutdir=tests/daemon`
Expected: FAIL — after the second reveal Alice still has 1000 (the `already_revealed` guard suppresses re-awarding) and Bob still has 0.

- [ ] **Step 3: Modify `reveal_correct` — reverse previous awards, record new awards, drop `already_revealed`**

In `daemon/poll/state.py`, replace the `reveal_correct` method (currently lines 78-141) with this version. Only three lines change vs. the current code, but show the full method to avoid ambiguity:

```python
    def reveal_correct(self, correct_indices: list[int], scores_obj) -> dict:
        correct_set = set(correct_indices)
        n = len(self.poll["options"]) if self.poll else 0
        all_indices = set(range(n))
        wrong_set = all_indices - correct_set
        multi = self.poll.get("multi", False) if self.poll else False
        now = datetime.now(timezone.utc)
        opened_at = self.poll_opened_at or now

        # Reverse the awards from the previous reveal_correct (if any). This makes
        # reveal_correct idempotent: when the host changes which option is correct,
        # points flow off prior winners before flowing onto new winners.
        for pid, prev_pts in self.awarded_points.items():
            scores_obj.add_score(pid, -prev_pts)
        self.awarded_points = {}

        correct_voters = set()
        for pid, vote in self.votes.items():
            voted = set(vote["option_indices"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                if max(0.0, (R - W) / len(correct_set)) > 0:
                    correct_voters.add(pid)
            else:
                if voted & correct_set:
                    correct_voters.add(pid)

        def _elapsed(pid: str) -> float:
            voted_at_str = self.votes[pid]["voted_at"]
            try:
                voted_at = datetime.fromisoformat(voted_at_str)
                return max(0.0, (voted_at - opened_at).total_seconds())
            except Exception:
                return 0.0

        elapsed_times = [_elapsed(p) for p in correct_voters]
        min_time = min(elapsed_times) if elapsed_times else 0.0

        for pid, vote in self.votes.items():
            voted = set(vote["option_indices"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                C = len(correct_set)
                ratio = max(0.0, (R - W) / C)
                if ratio == 0:
                    continue
            else:
                if not (voted & correct_set):
                    continue
                ratio = 1.0
            elapsed = _elapsed(pid)
            speed_window = min_time * (_SLOWEST_MULTIPLIER - 1)
            if speed_window > 0:
                decay = min(1.0, (elapsed - min_time) / speed_window)
            else:
                decay = 0.0
            speed_pts = round(_MAX_POINTS - (_MAX_POINTS - _MIN_POINTS) * decay)
            pts = round(speed_pts * ratio)
            if pts > 0:
                scores_obj.add_score(pid, pts)
                self.awarded_points[pid] = pts

        self.poll_correct_indices = list(correct_set)
        self._append_to_poll_md(correct_set)
        return {
            "correct_indices": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": {pid: v["option_indices"] for pid, v in self.votes.items()},
        }
```

The three behavior-relevant changes vs. the current method:

1. **Removed:** `already_revealed = self.poll_correct_indices is not None`
2. **Added** (after computing `opened_at`): the reverse-loop block + reset of `self.awarded_points`.
3. **Replaced** `if pts > 0 and not already_revealed: scores_obj.add_score(pid, pts)` with `if pts > 0: scores_obj.add_score(pid, pts); self.awarded_points[pid] = pts`.

- [ ] **Step 4: Run the failing test to verify it passes**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py::test_reveal_correct_twice_single_select_moves_points -v --confcutdir=tests/daemon`
Expected: PASS.

- [ ] **Step 5: Run the full poll-state test file to check no regressions**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py -v --confcutdir=tests/daemon`
Expected: All PASS. In particular, `test_reveal_correct_speed_scoring`, `test_reveal_correct_multi_proportional`, `test_reveal_correct_no_votes`, and `test_append_to_poll_md` must still pass — they only call `reveal_correct` once, so the new reversal loop is a no-op for them.

- [ ] **Step 6: Write the failing test for multi-select partial-credit re-reveal**

Append to `tests/daemon/test_poll_state.py`:

```python
def test_reveal_correct_twice_multi_select_partial_credit():
    """In multi-select polls, the partial-credit amount is what gets reversed."""
    ps = PollState()
    ps.create_poll("Q?", ["A", "B", "C", "D"], multi=True, correct_count=3)
    ps.open_poll(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    # Alice picks A,B,D. Bob picks C,D.
    ps.votes = {
        "alice": {"option_indices": [0, 1, 3], "voted_at": vote_time},
        "bob":   {"option_indices": [2, 3], "voted_at": vote_time},
    }
    scores = MockScores()

    # First reveal correct = {A,B,C}. Alice: R=2,W=1,ratio=(2-1)/3 → ~333. Bob: R=1,W=1,ratio=0 → 0.
    ps.reveal_correct([0, 1, 2], scores)
    alice_first = scores.scores.get("alice", 0)
    assert alice_first > 0
    assert scores.scores.get("bob", 0) == 0
    assert ps.awarded_points == {"alice": alice_first}

    # Second reveal correct = {C,D}. Alice: voted A,B,D → R=1,W=2,ratio=max(0,-1/2)=0 → 0.
    # Bob: voted C,D → R=2,W=0,ratio=2/2=1 → 1000.
    ps.reveal_correct([2, 3], scores)
    assert scores.scores.get("alice", 0) == 0
    assert scores.scores.get("bob") == _MAX_POINTS
    assert ps.awarded_points == {"bob": _MAX_POINTS}
```

- [ ] **Step 7: Run the multi-select test**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py::test_reveal_correct_twice_multi_select_partial_credit -v --confcutdir=tests/daemon`
Expected: PASS (the same `reveal_correct` change covers both single and multi-select paths).

- [ ] **Step 8: Write the failing test for empty correct set on second reveal**

Append to `tests/daemon/test_poll_state.py`:

```python
def test_reveal_correct_twice_empty_set_reverses_all():
    """If the host marks no options correct on the second reveal, all prior awards must be reversed."""
    ps = PollState()
    ps.create_poll("Q?", ["A", "B"])
    ps.open_poll(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    ps.votes = {"alice": {"option_indices": [0], "voted_at": vote_time}}
    scores = MockScores()

    ps.reveal_correct([0], scores)
    assert scores.scores["alice"] == _MAX_POINTS

    ps.reveal_correct([], scores)
    assert scores.scores.get("alice", 0) == 0
    assert ps.awarded_points == {}
    assert ps.poll_correct_indices == []
```

- [ ] **Step 9: Run the empty-set test**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_poll_state.py::test_reveal_correct_twice_empty_set_reverses_all -v --confcutdir=tests/daemon`
Expected: PASS.

- [ ] **Step 10: Run the full daemon test suite to check no other regression**

Run: `uv run --extra dev --extra daemon pytest tests/daemon -v --confcutdir=tests/daemon`
Expected: All PASS. Anything related to `poll_state.poll_correct_indices` truthiness needs particular attention.

- [ ] **Step 11: Commit**

```bash
git add daemon/poll/state.py tests/daemon/test_poll_state.py
git commit -m "feat(poll): rescore on host correct-answer change

reveal_correct is now idempotent: each call reverses the previous
awards from this poll, then re-applies fresh awards based on the
current correct_indices. The 'already_revealed' guard is gone.

Single-select, multi-select partial-credit, and empty-set paths
are all covered by new tests."
```

---

## Task 3: Add `awarded_points` to `PersistedPollState`

Match the existing pattern (`correct_indices`, `votes`, `opened_at`, …) so the snapshot model matches what the writer emits.

**Files:**
- Modify: `daemon/persisted_models.py:37-46`
- Test:   none for this task — covered indirectly by the snapshot writer test in Task 4.

- [ ] **Step 1: Add the field to `PersistedPollState`**

In `daemon/persisted_models.py`, locate `class PersistedPollState(PersistedModel):` (line 37). After the existing `votes:` field, add `awarded_points`:

```python
class PersistedPollState(PersistedModel):
    """Poll snapshot persisted in session state."""

    definition: dict[str, Any] | None = Field(default=None, description="Poll question and options as shown to participants")
    active: bool | None = None
    correct_indices: list[int] = Field(default_factory=list, description="Option indices marked as correct answers")
    opened_at: str | None = None
    end_timer_seconds: int | None = None
    end_timer_started_at: str | None = None
    votes: dict[str, Any] = Field(default_factory=dict, description="participant_uuid → chosen option ID(s)")
    awarded_points: dict[str, int] = Field(default_factory=dict, description="participant_uuid → points awarded by most recent reveal_correct")
```

- [ ] **Step 2: Verify the model still loads**

Run: `uv run --extra dev --extra daemon python -c "from daemon.persisted_models import PersistedPollState; m = PersistedPollState(); print(m.model_dump())"`
Expected: prints a dict that includes `'awarded_points': {}`.

- [ ] **Step 3: Run any model-related tests to confirm no regression**

Run: `uv run --extra dev --extra daemon pytest tests/daemon -v --confcutdir=tests/daemon -k "persist or model"`
Expected: All PASS (or "no tests collected" if there are no matching tests — that is OK).

Then run the full daemon suite:

Run: `uv run --extra dev --extra daemon pytest tests/daemon -v --confcutdir=tests/daemon`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add daemon/persisted_models.py
git commit -m "feat(poll): persist awarded_points in PersistedPollState

Mirrors the existing per-poll fields (correct_indices, votes, …) so
the snapshot model matches the writer in __main__.py."
```

---

## Task 4: Wire `awarded_points` into the snapshot writer

Add `awarded_points` to the `poll` dict produced by `_runtime_snapshot()` so it ends up in the on-disk session JSON.

**Files:**
- Modify: `daemon/__main__.py:216-224`
- Test:   `tests/daemon/test_daemon_state.py` (append a small snapshot test if a similar one exists nearby; otherwise inline at end).

- [ ] **Step 1: Inspect the existing snapshot test pattern**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_daemon_state.py -v --confcutdir=tests/daemon -k "poll"`
Read the matching test(s) in `tests/daemon/test_daemon_state.py` to mirror their fixture/style.

- [ ] **Step 2: Write the failing test**

Append to `tests/daemon/test_daemon_state.py` (adapt the surrounding imports/fixtures used by neighboring tests if needed):

```python
def test_runtime_snapshot_includes_awarded_points():
    """The snapshot writer must surface poll_state.awarded_points so it round-trips to disk."""
    from daemon.__main__ import _runtime_snapshot
    from daemon.poll.state import poll_state

    poll_state.create_poll("Q?", ["A", "B"])
    poll_state.open_poll(lambda: None)
    poll_state.awarded_points = {"alice": 750, "bob": 200}

    snap = _runtime_snapshot()

    assert "poll" in snap
    assert snap["poll"].get("awarded_points") == {"alice": 750, "bob": 200}

    # Cleanup: leave global poll_state empty for subsequent tests in the suite.
    poll_state.clear()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_daemon_state.py::test_runtime_snapshot_includes_awarded_points -v --confcutdir=tests/daemon`
Expected: FAIL with `AssertionError` because `awarded_points` is not in the emitted dict.

- [ ] **Step 4: Add `awarded_points` to the snapshot writer**

In `daemon/__main__.py`, locate the `poll` block in `_runtime_snapshot()` (around line 216-224):

```python
        "poll": {
            "definition": poll_state.poll,
            "active": poll_state.poll_active,
            "correct_indices": poll_state.poll_correct_indices or [],
            "opened_at": poll_opened_at,
            "timer_seconds": poll_state.poll_timer_seconds,
            "timer_started_at": poll_timer_started_at,
            "votes": dict(poll_state.votes),
        },
```

Add a new line after `"votes": dict(poll_state.votes),`:

```python
            "awarded_points": dict(poll_state.awarded_points),
```

The full block becomes:

```python
        "poll": {
            "definition": poll_state.poll,
            "active": poll_state.poll_active,
            "correct_indices": poll_state.poll_correct_indices or [],
            "opened_at": poll_opened_at,
            "timer_seconds": poll_state.poll_timer_seconds,
            "timer_started_at": poll_timer_started_at,
            "votes": dict(poll_state.votes),
            "awarded_points": dict(poll_state.awarded_points),
        },
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_daemon_state.py::test_runtime_snapshot_includes_awarded_points -v --confcutdir=tests/daemon`
Expected: PASS.

- [ ] **Step 6: Run the full daemon suite for regressions**

Run: `uv run --extra dev --extra daemon pytest tests/daemon -v --confcutdir=tests/daemon`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add daemon/__main__.py tests/daemon/test_daemon_state.py
git commit -m "feat(poll): write awarded_points into session snapshot

Snapshot writer now emits poll.awarded_points alongside
correct_indices/votes/etc. so it survives if/when poll restore is
wired up later."
```

---

## Task 5: Add BDD scenario covering host-changes-correct-answer

End-to-end coverage in the hermetic Docker test that exercises real daemon + Railway + browser. All required step definitions already exist; we only add Gherkin lines.

**Files:**
- Modify: `tests/docker/features/poll.feature`
- Test:   the same file (BDD self-tests).

- [ ] **Step 1: Add the scenario to the feature file**

In `tests/docker/features/poll.feature`, append at the end of the file (after the existing "Host sees live voted-count update as votes arrive" scenario):

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

Confirm by reading the file around the new scenario that no scenario separator (blank line) was missed and that the Background `Given a poll "Best language?" with options "Python;Java;Go"` from the top of the file applies — both `Java` and `Python` are valid options.

- [ ] **Step 2: Confirm no new step definitions are required**

Compare every Given/When/Then in the new scenario against the registered step definitions in `tests/docker/step_defs/test_poll.py`. Each one should already exist:

| Step | Existing definition |
|---|---|
| `a participant "Alice" selects "Java"` | `named_pax_selects` (regex `_NAMED_PAX_RE_SELECT`) |
| `a participant "Bob" selects "Python"` | `named_pax_selects` (regex `_NAMED_PAX_RE_SELECT`) |
| `the host closes the poll` | `host_closes_poll` |
| `the host marks "Java" as correct option` | `host_marks_correct` (registered for both `@given` and `@when`) |
| `Alice is awarded 1000 points` / `Bob is awarded 0 points` | `named_awarded` (regex `^(?P<name>...) is awarded (?P<n>\d+) points$`) — registered as `@then`, but BDD `And` after `Given` reuses the prior step type, so Given-level uses also resolve. **Note:** these lines appear in the `Given` block as `And`. Verify by running the scenario in step 4. If pytest-bdd refuses to bind a `@then` step in a Given block, register `named_awarded` for `@given` as well (one-line edit). |

- [ ] **Step 3: Run the new scenario in Docker**

Run: `bash tests/docker/run-hermetic.sh -k "Host changes the correct option" -s`
Expected: PASS, with the seq diagram extraction running (the scenario is `@seq`).

If `named_awarded` fails to bind in the Given block (BDD step-type mismatch), apply this minimal fix to `tests/docker/step_defs/test_poll.py`:

```python
@then(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+) is awarded (?P<n>\d+) points$"))
@given(parsers.re(r"^(?P<name>[A-Z][a-zA-Z]+) is awarded (?P<n>\d+) points$"))
def named_awarded(name, n):
    _wait_for_score(_participants[name], int(n))
```

(Add the `@given(...)` decorator above the existing `@then(...)`. Mirror the existing same-step dual decoration pattern used by, e.g., `the host marks "..." as correct option`.)

- [ ] **Step 4: Re-run hermetic if step definitions were updated**

Run: `bash tests/docker/run-hermetic.sh -k "Host changes the correct option" -s`
Expected: PASS.

- [ ] **Step 5: Run the full poll feature file to confirm no regression**

Run: `bash tests/docker/run-hermetic.sh -k "poll.feature" -s`
Expected: All scenarios in `poll.feature` PASS.

- [ ] **Step 6: Commit**

If only the feature file was changed:

```bash
git add tests/docker/features/poll.feature
git commit -m "test(poll): BDD scenario for host changing correct answer"
```

If `test_poll.py` also got the `@given` decorator fix:

```bash
git add tests/docker/features/poll.feature tests/docker/step_defs/test_poll.py
git commit -m "test(poll): BDD scenario for host changing correct answer

Allows the 'is awarded N points' step to bind in Given blocks too,
since the new scenario uses the assertion as a precondition before
flipping the correct answer."
```

---

## Task 6: Final verification + push to master

- [ ] **Step 1: Run the project pre-push parity script**

Run: `uv run --extra dev --extra daemon bash tests/check-all.sh`
Expected: All checks PASS.

- [ ] **Step 2: Run the full hermetic Docker suite**

Run: `bash tests/docker/run-hermetic.sh`
Expected: All PASS.

- [ ] **Step 3: Push directly to master**

```bash
git fetch origin master
git rebase origin/master
git push origin master
```

- [ ] **Step 4: Wait for production deploy**

Per project convention, wait for Railway to deploy and verify the production URL (see `CLAUDE.md` → "Production Deployment") is live before declaring the task done. Use the `wait-for-deploy` skill if available.

---

## Self-Review

**Spec coverage:**

| Spec section | Implemented in |
|---|---|
| Goal: idempotent `reveal_correct` | Task 2 |
| `awarded_points` field added/reset | Task 1 |
| Reverse-then-apply algorithm | Task 2 |
| Drop `already_revealed` | Task 2 |
| `PersistedPollState.awarded_points` field | Task 3 |
| Snapshot writer emits `awarded_points` | Task 4 |
| Note: poll restore not wired (out of scope) | Confirmed in Task 3/4 — no `sync_from_restore` change |
| BDD scenario "Host changes the correct option, points re-flow" | Task 5 |
| Daemon unit tests: single-select, multi-select, empty-set, reset on create/clear | Tasks 1 + 2 (4 new tests) |
| `ScoresUpdatedMsg` / `PollCorrectRevealedMsg` unchanged | Task 2 (no change to the broadcast in `daemon/poll/router.py`) |

**Type/name consistency:** `awarded_points: dict[str, int]` is used identically in `PollState`, `PersistedPollState`, and the snapshot writer. The BDD scenario uses option text matching the Background poll (`Java`, `Python`).

**Placeholder scan:** No "TBD", "TODO", "implement later", or unspecified error handling. Each step shows the exact code or command to run.
