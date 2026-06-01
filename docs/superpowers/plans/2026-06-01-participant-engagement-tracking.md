# Participant Engagement Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track per-participant active time / visits / clicks per view, aggregate it in session state, and surface it to the host as a live "👁 N active" footer badge with a cumulative breakdown popover.

**Architecture:** The participant page accumulates per-view metrics locally and POSTs deltas (≤ every 30s, plus on hide/unload) to a new daemon REST endpoint. The daemon merges deltas into runtime `ParticipantState`, which the existing 3-second snapshot loop persists into `session-state.json` via `PersistedParticipant.engagement`. Engagement rides to the host on the existing `participant_list_updated` message (no new WS type); the host browser derives the live "active now" count locally from a server-stamped `last_active_at` and renders the badge.

**Tech Stack:** Python 3 + FastAPI + Pydantic v2 (daemon); plain HTML + vanilla JS, no build step (participant + host frontends); pytest (`--confcutdir=tests/daemon`).

**Reference spec:** `docs/superpowers/specs/2026-06-01-participant-engagement-tracking-design.md`

---

## File Structure

**Daemon (backend):**
- `daemon/persisted_models.py` — add `ViewEngagement` model + `PersistedParticipant.engagement` field (persisted cumulative metrics).
- `daemon/participant/state.py` — add runtime `engagement` / `last_active_at` / `last_view` dicts to `ParticipantState`; clear them in `reset()`; read `engagement` back in `sync_from_restore()`.
- `daemon/__main__.py` — extend `_build_runtime_session_snapshot()` to persist each participant's `engagement`.
- `daemon/participant/router.py` — new `ViewEngagementDelta` / `ActivityReportRequest` models + `POST /api/participant/activity` handler.
- `daemon/host_state_router.py` — surface `engagement` / `last_active_at` / `last_view` per participant in `_build_host_participants_list()`; add matching optional fields to `HostParticipant`.
- `docs/openapi.yaml`, `API.md` — regenerated artifacts (new endpoint + `HostParticipant` change).

**Frontend:**
- `static/participant.html` — inline `Engagement` module + `showView` hook + `Engagement.init()` call.
- `static/host.html` — new engagement badge + popover markup in `.host-footer-left`.
- `static/host.js` — capture engagement from `participants`, compute live count, render badge + popover, register hover, start ticker.
- (`static/host.css` — **no change**; reuses existing `.badge`, `.badge.empty`, `.slides-catalog-popover`, `.activity-log-popover` rules.)

**Tests:**
- `tests/daemon/test_persisted_models.py` (new) — engagement model round-trip.
- `tests/daemon/test_participant_state.py` (new) — `sync_from_restore` / `reset` engagement.
- `tests/daemon/test_runtime_snapshot.py` (new) — snapshot includes engagement.
- `tests/daemon/test_participant_router.py` (existing) — add activity-endpoint tests.
- `tests/daemon/test_host_state_router.py` (new or existing) — `_build_host_participants_list` includes engagement.

**Docs:** `ARCHITECTURE.md`, `backlog.md`.

**Test command (Apple Silicon, hook parity):**
```bash
arch -arm64 uv run --extra dev --extra daemon python -m pytest <path> --confcutdir=tests/daemon -q
```
(Drop `arch -arm64` on Intel; plain `python -m pytest` also works if the venv is already active.)

---

## Task 1: Persisted engagement model

**Files:**
- Modify: `daemon/persisted_models.py` (add `ViewEngagement` before `PersistedParticipant` at line 28; add `engagement` field to `PersistedParticipant`)
- Test: `tests/daemon/test_persisted_models.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_persisted_models.py`:

```python
"""Tests for persisted Pydantic models — engagement metrics."""

from daemon.persisted_models import PersistedParticipant, ViewEngagement


def test_view_engagement_defaults_to_zero():
    ve = ViewEngagement()
    assert (ve.seconds, ve.visits, ve.clicks) == (0, 0, 0)


def test_persisted_participant_carries_engagement():
    p = PersistedParticipant.model_validate(
        {
            "name": "Alice",
            "engagement": {"slides": {"seconds": 30, "visits": 2, "clicks": 5}},
        }
    )
    assert p.engagement["slides"].seconds == 30
    assert p.engagement["slides"].visits == 2
    assert p.engagement["slides"].clicks == 5


def test_persisted_participant_engagement_json_round_trip():
    p = PersistedParticipant.model_validate(
        {"name": "Bob", "engagement": {"notes": {"seconds": 12, "visits": 1, "clicks": 0}}}
    )
    p2 = PersistedParticipant.model_validate(p.model_dump(mode="json"))
    assert p2.engagement["notes"].seconds == 12


def test_persisted_participant_defaults_empty_engagement():
    p = PersistedParticipant.model_validate({"name": "Carol"})
    assert p.engagement == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_persisted_models.py --confcutdir=tests/daemon -q`
Expected: FAIL with `ImportError: cannot import name 'ViewEngagement'`.

- [ ] **Step 3: Write minimal implementation**

In `daemon/persisted_models.py`, insert the `ViewEngagement` class immediately before `class PersistedParticipant` (currently line 28):

```python
class ViewEngagement(PersistedModel):
    """Per-view cumulative engagement metrics for one participant."""

    seconds: int = 0
    visits: int = 0
    clicks: int = 0
```

Then add the `engagement` field to `PersistedParticipant` (after the `location` field):

```python
class PersistedParticipant(PersistedModel):
    """Participant identity persisted in session snapshots."""

    name: str | None = None
    avatar: str | None = None
    score: int | float | None = None
    location: str | None = None
    engagement: dict[str, ViewEngagement] = Field(default_factory=dict)
```

(`Field` is already imported at the top of the file: `from pydantic import BaseModel, ConfigDict, Field, model_validator`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_persisted_models.py --confcutdir=tests/daemon -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add daemon/persisted_models.py tests/daemon/test_persisted_models.py
git commit -m "feat(engagement): persist per-view engagement on PersistedParticipant

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Runtime ParticipantState fields

**Files:**
- Modify: `daemon/participant/state.py` (`ParticipantState.__init__` ~line 32; `sync_from_restore` ~line 46; `reset` ~line 134)
- Test: `tests/daemon/test_participant_state.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_participant_state.py`:

```python
"""Tests for ParticipantState engagement runtime fields."""

from daemon.participant.state import ParticipantState


def test_new_state_has_empty_engagement_maps():
    ps = ParticipantState()
    assert ps.engagement == {}
    assert ps.last_active_at == {}
    assert ps.last_view == {}


def test_sync_from_restore_reads_engagement():
    ps = ParticipantState()
    ps.sync_from_restore(
        {
            "participants": {
                "u1": {
                    "name": "Alice",
                    "engagement": {"notes": {"seconds": 12, "visits": 1, "clicks": 0}},
                }
            }
        }
    )
    assert ps.participant_names["u1"] == "Alice"
    assert ps.engagement["u1"]["notes"]["seconds"] == 12


def test_reset_clears_engagement_and_liveness():
    ps = ParticipantState()
    ps.engagement["u1"] = {"slides": {"seconds": 5, "visits": 1, "clicks": 1}}
    ps.last_active_at["u1"] = 123.0
    ps.last_view["u1"] = "slides"
    ps.reset()
    assert ps.engagement == {}
    assert ps.last_active_at == {}
    assert ps.last_view == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_state.py --confcutdir=tests/daemon -q`
Expected: FAIL with `AttributeError: 'ParticipantState' object has no attribute 'engagement'`.

- [ ] **Step 3: Write minimal implementation**

In `daemon/participant/state.py`, add three dicts at the end of `__init__` (after `self.emoji_counters`):

```python
    def __init__(self):
        self._lock = threading.Lock()
        self.participant_names: dict[str, str] = {}
        self.participant_avatars: dict[str, str] = {}
        self.participant_universes: dict[str, str] = {}
        self.online_participants: set[str] = set()
        self.scores: dict[str, int] = {}
        self.locations: dict[str, str] = {}
        self.location_timezones: dict[str, str] = {}
        self.location_countries: dict[str, str] = {}
        self.mode: str = "workshop"
        self.current_activity: str = "none"
        self.emoji_counters: dict[str, int] = {}
        # Engagement: uuid -> {view -> {seconds, visits, clicks}} (cumulative, persisted)
        self.engagement: dict[str, dict] = {}
        # Liveness (ephemeral, NOT persisted): host derives "active now" from these
        self.last_active_at: dict[str, float] = {}
        self.last_view: dict[str, str] = {}
```

In `sync_from_restore`, inside the `if isinstance(participants, dict):` block, add `self.engagement.clear()` to the existing clear group:

```python
            if isinstance(participants, dict):
                self.participant_names.clear()
                self.participant_avatars.clear()
                self.online_participants.clear()
                self.scores.clear()
                self.locations.clear()
                self.location_timezones.clear()
                self.location_countries.clear()
                self.engagement.clear()
```

…and inside the per-participant `for pid, raw in participants.items():` loop, after the `location_country` extraction block, add:

```python
                    engagement = raw.get("engagement")
                    if isinstance(engagement, dict):
                        self.engagement[str(pid)] = engagement
```

In `reset`, add three clears (inside the `with self._lock:` block, after `self.emoji_counters.clear()`):

```python
            self.emoji_counters.clear()
            self.engagement.clear()
            self.last_active_at.clear()
            self.last_view.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_state.py --confcutdir=tests/daemon -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add daemon/participant/state.py tests/daemon/test_participant_state.py
git commit -m "feat(engagement): add engagement/liveness runtime maps to ParticipantState

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2b: Preserve engagement across `snapshot()`-based saves

**Why this exists (discovered during implementation):** `daemon/emoji/router.py:37` persists session state via `save_session_state(folder, participant_state.snapshot())`, and `save_session_state` (daemon/session_state.py:337) replaces the whole file (only `session_id` + meta keys are preserved from disk). `ParticipantState.snapshot()` emits **flat** per-attribute maps (`participant_names`, `scores`, …) that the model's `_normalize_legacy_participant_maps` validator folds into nested `participants[uuid]`. Engagement is neither emitted by `snapshot()` nor folded by the normalizer, so a `snapshot()`-based save would drop engagement from `session-state.json`; a daemon kill before the next 3s periodic save would lose **all** session engagement (non-re-derivable). Fix: treat engagement exactly like `name`/`avatar`/`score`/`location` — emit a flat `engagement` map from `snapshot()` and fold it in the normalizer (nested values win via `setdefault`).

**Files:**
- Modify: `daemon/participant/state.py` (`snapshot()` ~line 127)
- Modify: `daemon/persisted_models.py` (`_normalize_legacy_participant_maps`, the flat-map fold block ~lines 214-248)
- Test: append to `tests/daemon/test_participant_state.py` and `tests/daemon/test_persisted_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/daemon/test_participant_state.py`:

```python
def test_snapshot_includes_engagement():
    ps = ParticipantState()
    ps.engagement["u1"] = {"slides": {"seconds": 5, "visits": 1, "clicks": 2}}
    snap = ps.snapshot()
    assert snap["engagement"] == {"u1": {"slides": {"seconds": 5, "visits": 1, "clicks": 2}}}
```

Append to `tests/daemon/test_persisted_models.py` (add `PersistedSessionState` to the import line: `from daemon.persisted_models import PersistedParticipant, PersistedSessionState, ViewEngagement`):

```python
def test_normalizer_folds_flat_engagement_into_participants():
    state = PersistedSessionState.model_validate(
        {
            "session_id": "t",
            "participant_names": {"u1": "Alice"},
            "engagement": {"u1": {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}},
        }
    )
    assert state.participants["u1"].engagement["slides"].seconds == 30


def test_nested_engagement_wins_over_flat_legacy_map():
    state = PersistedSessionState.model_validate(
        {
            "session_id": "t",
            "participants": {
                "u1": {"name": "Alice", "engagement": {"slides": {"seconds": 99, "visits": 9, "clicks": 9}}}
            },
            "engagement": {"u1": {"slides": {"seconds": 1, "visits": 1, "clicks": 1}}},
        }
    )
    assert state.participants["u1"].engagement["slides"].seconds == 99
```

(If `PersistedSessionState.model_validate` rejects this dict for a missing required field other than `session_id`, add the minimal required field(s) to the test inputs — the assertion target is the engagement folding, not the rest of the model.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_state.py tests/daemon/test_persisted_models.py --confcutdir=tests/daemon -q`
Expected: the 3 new tests FAIL (`KeyError: 'engagement'` in snapshot; engagement absent from folded participants).

- [ ] **Step 3: Implement**

(a) In `daemon/participant/state.py`, `snapshot()`, add an `engagement` entry to the returned dict (after `"emoji_counters": dict(self.emoji_counters),`):

```python
                "emoji_counters": dict(self.emoji_counters),
                "engagement": {pid: dict(views) for pid, views in self.engagement.items()},
```

(b) In `daemon/persisted_models.py`, `_normalize_legacy_participant_maps`: after the `locations` flat-map block (the `_locations_raw` / `locations` lines), add:

```python
        _engagement_raw = data.get("engagement")
        engagement_map: dict = _engagement_raw if isinstance(_engagement_raw, dict) else {}
```

Add engagement ids to the `all_ids` union (extend the existing `all_ids |= ...` lines):

```python
        all_ids |= {str(pid) for pid in engagement_map}
```

Inside the `for pid in all_ids:` loop, after the `location` `setdefault` block, add:

```python
            eng = engagement_map.get(pid)
            if isinstance(eng, dict) and eng:
                row.setdefault("engagement", eng)
```

After the loop, before `data["participants"] = participants`, drop the now-folded flat map so it is not persisted as a redundant top-level extra:

```python
        data.pop("engagement", None)
        data["participants"] = participants
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_state.py tests/daemon/test_persisted_models.py --confcutdir=tests/daemon -q`
Expected: all PASS (Task 1 + Task 2 + the 3 new = 10 passed).

- [ ] **Step 5: Guard against regression in the broader load path**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon -k "persist or session or participant" --confcutdir=tests/daemon -q`
Expected: PASS (the normalizer change does not break existing session-state loading).

- [ ] **Step 6: Commit**

```bash
git add daemon/participant/state.py daemon/persisted_models.py tests/daemon/test_participant_state.py tests/daemon/test_persisted_models.py
git commit -m "fix(engagement): preserve engagement across snapshot()-based session saves

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Persist engagement in the snapshot builder

**Files:**
- Modify: `daemon/__main__.py` (`_build_runtime_session_snapshot`, lines ~155-189)
- Test: `tests/daemon/test_runtime_snapshot.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_runtime_snapshot.py`:

```python
"""Tests that the runtime snapshot builder persists participant engagement."""

from daemon.__main__ import _build_runtime_session_snapshot
from daemon.participant.state import participant_state


def test_snapshot_includes_participant_engagement():
    participant_state.reset()
    try:
        participant_state.participant_names["u1"] = "Alice"
        participant_state.engagement["u1"] = {
            "slides": {"seconds": 30, "visits": 2, "clicks": 5}
        }
        snap = _build_runtime_session_snapshot(session_name="test-session")
        assert snap["participants"]["u1"]["engagement"] == {
            "slides": {"seconds": 30, "visits": 2, "clicks": 5}
        }
    finally:
        participant_state.reset()


def test_snapshot_persists_engagement_only_participant():
    participant_state.reset()
    try:
        # A participant that reported engagement before being named must still persist.
        participant_state.engagement["u2"] = {"notes": {"seconds": 9, "visits": 1, "clicks": 0}}
        snap = _build_runtime_session_snapshot(session_name="test-session")
        assert snap["participants"]["u2"]["engagement"]["notes"]["seconds"] == 9
    finally:
        participant_state.reset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_runtime_snapshot.py --confcutdir=tests/daemon -q`
Expected: FAIL with `KeyError: 'engagement'` (the snapshot row has no engagement key).

- [ ] **Step 3: Write minimal implementation**

In `daemon/__main__.py`, in `_build_runtime_session_snapshot`, add engagement uuids to the `participant_ids` union and write the engagement into each row. The relevant section becomes:

```python
    participants_payload: dict[str, dict[str, object]] = {}
    participant_ids = set(participant_state.participant_names)
    participant_ids |= set(participant_state.participant_avatars)
    from daemon.scores import scores as daemon_scores
    participant_ids |= set(daemon_scores.scores)
    participant_ids |= set(participant_state.locations)
    participant_ids |= set(participant_state.location_timezones)
    participant_ids |= set(participant_state.location_countries)
    participant_ids |= set(participant_state.engagement)
    for pid in participant_ids:
        row: dict[str, object] = {}
        if pid in participant_state.participant_names:
            row["name"] = participant_state.participant_names[pid]
        if pid in participant_state.participant_avatars:
            row["avatar"] = participant_state.participant_avatars[pid]
        if pid in daemon_scores.scores:
            row["score"] = daemon_scores.scores[pid]
        if pid in participant_state.locations:
            row["location"] = participant_state.locations[pid]
        if pid in participant_state.location_timezones:
            row["location_tz"] = participant_state.location_timezones[pid]
        if pid in participant_state.location_countries:
            row["location_country"] = participant_state.location_countries[pid]
        if pid in participant_state.engagement:
            row["engagement"] = participant_state.engagement[pid]
        participants_payload[pid] = row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_runtime_snapshot.py --confcutdir=tests/daemon -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add daemon/__main__.py tests/daemon/test_runtime_snapshot.py
git commit -m "feat(engagement): persist participant engagement in session snapshot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Activity report endpoint

**Files:**
- Modify: `daemon/participant/router.py` (imports ~line 18; request models after `LocationRequest` ~line 69; handler after `rename_participant` ~line 577)
- Test: `tests/daemon/test_participant_router.py` (existing — append a `TestActivity` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/daemon/test_participant_router.py` (it already defines the `fresh_state` and `client` fixtures used here):

```python
class TestActivity:
    def test_merges_deltas_and_stamps_liveness(self, client, fresh_state):
        resp = client.post(
            "/api/participant/activity",
            json={
                "current_view": "slides",
                "deltas": {"slides": {"seconds": 10, "visits": 1, "clicks": 3}},
            },
            headers={"X-Participant-ID": "u1"},
        )
        assert resp.status_code == 204
        assert fresh_state.engagement["u1"]["slides"] == {
            "seconds": 10,
            "visits": 1,
            "clicks": 3,
        }
        assert fresh_state.last_view["u1"] == "slides"
        assert fresh_state.last_active_at["u1"] > 0

    def test_accumulates_across_reports(self, client, fresh_state):
        client.post(
            "/api/participant/activity",
            json={"current_view": "notes", "deltas": {"notes": {"seconds": 5, "visits": 1, "clicks": 0}}},
            headers={"X-Participant-ID": "u1"},
        )
        client.post(
            "/api/participant/activity",
            json={"current_view": "notes", "deltas": {"notes": {"seconds": 7, "visits": 0, "clicks": 2}}},
            headers={"X-Participant-ID": "u1"},
        )
        assert fresh_state.engagement["u1"]["notes"] == {"seconds": 12, "visits": 1, "clicks": 2}

    def test_missing_participant_id_returns_400(self, client):
        resp = client.post(
            "/api/participant/activity",
            json={"current_view": "slides", "deltas": {}},
        )
        assert resp.status_code == 400

    def test_unknown_view_is_ignored(self, client, fresh_state):
        client.post(
            "/api/participant/activity",
            json={"current_view": "slides", "deltas": {"bogus": {"seconds": 99, "visits": 1, "clicks": 1}}},
            headers={"X-Participant-ID": "u1"},
        )
        assert "bogus" not in fresh_state.engagement.get("u1", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_router.py::TestActivity --confcutdir=tests/daemon -q`
Expected: FAIL — all four error/fail with 404 (route not found).

- [ ] **Step 3: Write minimal implementation**

In `daemon/participant/router.py`:

(a) Ensure `time` is imported and `Field` is imported. The current import block has `from pydantic import BaseModel`. Change it to:

```python
from pydantic import BaseModel, Field
```

…and add `import time` to the stdlib import block (alongside `import secrets`).

(b) After the `LocationRequest` model (line 69), add the request models and the known-view set:

```python
_KNOWN_VIEWS = {
    "activity",
    "slides",
    "summary",
    "notes",
    "agenda",
    "feedback",
    "upload-paste",
    "files",
}


class ViewEngagementDelta(BaseModel):
    seconds: int = Field(0, ge=0)
    visits: int = Field(0, ge=0)
    clicks: int = Field(0, ge=0)


class ActivityReportRequest(BaseModel):
    current_view: str = ""
    deltas: dict[str, ViewEngagementDelta] = {}
```

(c) After the `rename_participant` handler (line 577), add the activity handler:

```python
@router.post("/activity", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def report_activity(request: Request, body: ActivityReportRequest):
    """Merge a participant's per-view engagement deltas (active seconds/visits/clicks).

    Called by the participant page at most every ~30s while active, and on
    tab-hide/unload. Idle/backgrounded tabs send nothing.
    """
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    ps = participant_state
    bucket = ps.engagement.setdefault(pid, {})
    for view, delta in body.deltas.items():
        if view not in _KNOWN_VIEWS:
            continue
        cur = bucket.setdefault(view, {"seconds": 0, "visits": 0, "clicks": 0})
        cur["seconds"] += delta.seconds
        cur["visits"] += delta.visits
        cur["clicks"] += delta.clicks

    ps.last_active_at[pid] = time.time() * 1000.0  # epoch ms; host compares to Date.now()
    if body.current_view:
        ps.last_view[pid] = body.current_view

    await _notify_host_participant_list()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

(No explicit `save_session_state` call — the 3-second snapshot loop in `daemon/__main__.py` persists `participant_state.engagement`, exactly as `rename_participant` relies on it for `participant_names`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_participant_router.py::TestActivity --confcutdir=tests/daemon -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add daemon/participant/router.py tests/daemon/test_participant_router.py
git commit -m "feat(engagement): POST /api/participant/activity merges per-view deltas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Surface engagement to the host

**Files:**
- Modify: `daemon/host_state_router.py` (`HostParticipant` ~line 37; `_build_host_participants_list` ~line 138)
- Test: `tests/daemon/test_host_state_router.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_host_state_router.py`:

```python
"""Tests that the host participant list surfaces engagement + liveness."""

from daemon.host_state_router import _build_host_participants_list
from daemon.participant.state import participant_state


def test_host_list_includes_engagement_and_liveness():
    participant_state.reset()
    try:
        participant_state.participant_names["u1"] = "Alice"
        participant_state.engagement["u1"] = {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}
        participant_state.last_active_at["u1"] = 1700000000000.0
        participant_state.last_view["u1"] = "slides"
        rows = _build_host_participants_list()
        row = next(r for r in rows if r["uuid"] == "u1")
        assert row["engagement"] == {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}
        assert row["last_active_at"] == 1700000000000.0
        assert row["last_view"] == "slides"
    finally:
        participant_state.reset()


def test_host_list_defaults_when_no_engagement():
    participant_state.reset()
    try:
        participant_state.participant_names["u9"] = "Bob"
        rows = _build_host_participants_list()
        row = next(r for r in rows if r["uuid"] == "u9")
        assert row["engagement"] == {}
        assert row["last_active_at"] == 0
        assert row["last_view"] == ""
    finally:
        participant_state.reset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_host_state_router.py --confcutdir=tests/daemon -q`
Expected: FAIL with `KeyError: 'engagement'`.

- [ ] **Step 3: Write minimal implementation**

In `daemon/host_state_router.py`, add the three optional fields to `HostParticipant`:

```python
class HostParticipant(BaseModel):
    uuid: str
    name: str
    score: int
    location: str
    location_tz: str = ""
    location_country: str = ""
    avatar: str
    paste_texts: list[PasteEntry] = []
    received_files: list[UploadedFileEntry] = []
    engagement: dict[str, dict] = {}
    last_active_at: float = 0
    last_view: str = ""
```

In `_build_host_participants_list`, add the three keys to the per-participant `entry` dict (after the `"online"` key):

```python
        entry = {
            "uuid": pid,
            "name": ps.participant_names.get(pid, f"Guest {pid[:8]}"),
            "score": daemon_scores.scores.get(pid, 0),
            "location": ps.locations.get(pid, ""),
            "location_tz": ps.location_timezones.get(pid, ""),
            "location_country": ps.location_countries.get(pid, ""),
            "avatar": ps.participant_avatars.get(pid, ""),
            "online": pid in ps.online_participants,
            "engagement": ps.engagement.get(pid, {}),
            "last_active_at": ps.last_active_at.get(pid, 0),
            "last_view": ps.last_view.get(pid, ""),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_host_state_router.py --confcutdir=tests/daemon -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add daemon/host_state_router.py tests/daemon/test_host_state_router.py
git commit -m "feat(engagement): include engagement + liveness in host participant list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Regenerate API contract artifacts

**Files:**
- Modify (regenerated): `docs/openapi.yaml`, `API.md`

The daemon OpenAPI contract test (`tests/daemon/test_api_contract.py`) compares the live FastAPI schema against `docs/openapi.yaml`. The new `POST /api/participant/activity` route and the `HostParticipant` field additions change the schema, so the snapshot must be regenerated.

- [ ] **Step 1: Confirm the contract test currently fails (drift detected)**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_api_contract.py --confcutdir=tests/daemon -q`
Expected: FAIL — the live schema now contains `/api/participant/activity` (and engagement fields) not present in the snapshot.

- [ ] **Step 2: Regenerate the OpenAPI snapshot**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m tests.daemon.test_api_contract --regenerate`
Expected: writes the updated `docs/openapi.yaml`.

- [ ] **Step 3: Regenerate API.md from contracts**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 scripts/generate_apis_md.py --output API.md`
Expected: `API.md` updated with the new endpoint.

- [ ] **Step 4: Verify the contract test now passes**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon/test_api_contract.py --confcutdir=tests/daemon -q`
Expected: PASS.

- [ ] **Step 5: Sanity-check the diff**

Run: `git diff --stat docs/openapi.yaml API.md`
Expected: both files changed; `git diff docs/openapi.yaml` shows the new `/api/participant/activity` path and the `engagement`/`last_active_at`/`last_view` schema additions, and nothing unrelated.

- [ ] **Step 6: Commit**

```bash
git add docs/openapi.yaml API.md
git commit -m "docs(engagement): regenerate OpenAPI + API.md for activity endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Participant-side Engagement tracker

**Files:**
- Modify: `static/participant.html` (insert `Engagement` IIFE immediately before `function showView(name)` at line 2016; add hook inside `showView` after `setActive(name);` at line 2029; add `Engagement.init();` after `_connectWS();` at line 2647)

> No JS unit-test harness exists in this repo (no build step, vanilla JS). This task is implement-then-verify-in-browser; automated coverage of the end-to-end flow is the optional hermetic e2e in Task 10.

- [ ] **Step 1: Add the `Engagement` module**

In `static/participant.html`, immediately **before** `function showView(name) {` (line 2016), insert:

```javascript
// ===== Participant engagement tracking =====
// Accumulates per-view active time/visits/clicks and flushes deltas to the
// daemon (≤ every 30s while active, plus on tab-hide/unload). "Active" = tab
// visible AND a real interaction within the last 60s. Idle/hidden tabs send nothing.
var Engagement = (function() {
  var IDLE_MS = 60000;
  var FLUSH_MS = 30000;
  var pending = {};          // view -> {seconds, visits, clicks} not yet flushed
  var currentView = null;
  var lastInteractionAt = 0;

  function _bucket(view) {
    if (!pending[view]) pending[view] = { seconds: 0, visits: 0, clicks: 0 };
    return pending[view];
  }
  function _mark() { lastInteractionAt = Date.now(); }
  function _isActive() {
    return document.visibilityState === 'visible' && (Date.now() - lastInteractionAt) < IDLE_MS;
  }
  function _tick() {
    if (currentView && _isActive()) _bucket(currentView).seconds += 1;
  }
  function _flush() {
    var deltas = {};
    var any = false;
    for (var v in pending) {
      var d = pending[v];
      if (d.seconds || d.visits || d.clicks) { deltas[v] = d; any = true; }
    }
    if (!any || !_sessionId) return;
    pending = {};
    try {
      fetch('/' + _sessionId + '/api/participant/activity', {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-Participant-ID': _myUUID },
        body: JSON.stringify({ current_view: currentView || '', deltas: deltas })
      }).catch(function() {});
    } catch (e) {}
  }
  function onView(name) {
    if (name === currentView) return;
    var isInitial = (currentView === null);
    currentView = name;
    _mark();
    if (!isInitial && document.visibilityState === 'visible') _bucket(name).visits += 1;
  }
  function _onClick() {
    if (currentView) _bucket(currentView).clicks += 1;
    _mark();
  }
  function init() {
    ['mousemove', 'scroll', 'keydown', 'touchstart'].forEach(function(ev) {
      document.addEventListener(ev, _mark, { passive: true });
    });
    document.addEventListener('click', _onClick, true);
    document.addEventListener('visibilitychange', function() {
      if (document.visibilityState === 'hidden') _flush(); else _mark();
    });
    window.addEventListener('pagehide', _flush);
    _mark();
    setInterval(_tick, 1000);
    setInterval(_flush, FLUSH_MS);
  }
  return { init: init, onView: onView };
})();
```

- [ ] **Step 2: Hook `showView` and bootstrap `init`**

In `showView`, immediately after the existing `setActive(name);` line (line 2029), add:

```javascript
  setActive(name);
  Engagement.onView(name);
```

After the `_connectWS();` call (line 2647), add:

```javascript
  _connectWS();
  Engagement.init();
```

- [ ] **Step 3: Syntax check**

Run: `node --check static/participant.html 2>/dev/null || node -e "require('fs').readFileSync('static/participant.html','utf8')" && echo "read-ok"`

Because `participant.html` is HTML (not pure JS), `node --check` will not parse it. Instead, verify the inserted JS block parses by extracting nothing — rely on the browser load in Step 4. (Acceptable: there is no JS build step in this project.)

- [ ] **Step 4: Verify in the browser**

Start the daemon if not running (`python3 -m daemon`) and open the participant page (local host page is `http://localhost:8081/`; participants join via the session URL). Then:
1. Open DevTools → Network, filter `activity`.
2. Switch between Slides / Notes / Summary / Files, click around, wait ~30s.
3. Confirm a `POST .../api/participant/activity` fires (status 204) with a body like `{"current_view":"notes","deltas":{"notes":{"seconds":...,"visits":...,"clicks":...}}}`.
4. Switch the tab to the background for >60s with no interaction → confirm **no** further POSTs while hidden/idle.
5. Confirm DevTools Console shows no errors.

- [ ] **Step 5: Commit**

```bash
git add static/participant.html
git commit -m "feat(engagement): participant-side per-view active-time tracker

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Host engagement badge + popover

**Files:**
- Modify: `static/host.html` (add badge block in `.host-footer-left`, after the `summary-badge` span at line 335)
- Modify: `static/host.js` (capture call at top of `handleWSMessage` ~line 316; new functions after `_renderSlidesLogPopover` ~line 1008; hover + ticker registration inside `_setupActivityLogHovers` ~line 1021)

- [ ] **Step 1: Add the badge markup**

In `static/host.html`, inside `.host-footer-left`, immediately after the `summary-badge` span (line 335), add:

```html
  <div id="engagement-hover" class="slides-catalog-hover" style="position:relative;">
    <span id="engagement-badge" class="badge empty footer-tooltip-target" style="font-size:0.85rem; cursor:default; gap:.3rem;">👁<span id="engagement-count"></span></span>
    <div id="engagement-popover" class="slides-catalog-popover activity-log-popover">
      <div id="engagement-content" class="slides-catalog-content"></div>
    </div>
  </div>
```

- [ ] **Step 2: Capture engagement from incoming `participants`**

In `static/host.js`, at the very top of `function handleWSMessage(msg) {` (line 316), add the first line of the body:

```javascript
function handleWSMessage(msg) {
    if (Array.isArray(msg.participants)) _captureEngagement(msg.participants);
    if (msg.type === 'reload') {
```

(This fires for both the initial `state` message — fetched on WS open — and every `participant_list_updated` push, since both carry a `participants` array.)

- [ ] **Step 3: Add the badge render functions**

In `static/host.js`, immediately after `_renderSlidesLogPopover` ends (line 1008), add:

```javascript
// ===== Participant engagement badge =====
var _engagementByPid = {};
var _engagementTotal = 0;
var ENGAGEMENT_FRESH_MS = 75000;  // 30s flush + 60s idle slack
var ENGAGEMENT_VIEW_LABELS = {
  slides: 'Slides', notes: 'Notes', summary: 'Summary', files: 'Files',
  agenda: 'Agenda', activity: 'Activity', 'upload-paste': 'Upload', feedback: 'Feedback'
};

function _captureEngagement(participants) {
  var map = {};
  for (var i = 0; i < participants.length; i++) {
    var p = participants[i];
    if (!p || !p.uuid) continue;
    map[p.uuid] = {
      engagement: p.engagement || {},
      last_active_at: p.last_active_at || 0,
      last_view: p.last_view || ''
    };
  }
  _engagementByPid = map;
  _engagementTotal = participants.length;
  renderEngagementBadge();
}

function _engagementAggregate() {
  var now = Date.now();
  var activeByView = {};
  var totals = {};
  var activeCount = 0;
  for (var pid in _engagementByPid) {
    var rec = _engagementByPid[pid];
    if (rec.last_active_at && (now - rec.last_active_at) < ENGAGEMENT_FRESH_MS) {
      activeCount++;
      if (rec.last_view) activeByView[rec.last_view] = (activeByView[rec.last_view] || 0) + 1;
    }
    var eng = rec.engagement || {};
    for (var v in eng) {
      var d = eng[v];
      if (!totals[v]) totals[v] = { seconds: 0, visits: 0, clicks: 0 };
      totals[v].seconds += d.seconds || 0;
      totals[v].visits += d.visits || 0;
      totals[v].clicks += d.clicks || 0;
    }
  }
  return { activeByView: activeByView, totals: totals, activeCount: activeCount };
}

function renderEngagementBadge() {
  var badge = document.getElementById('engagement-badge');
  var countEl = document.getElementById('engagement-count');
  if (!badge || !countEl) return;
  var agg = _engagementAggregate();
  if (agg.activeCount > 0) {
    countEl.textContent = agg.activeCount;
    badge.className = 'badge connected footer-tooltip-target';
    _setFooterBadgeTooltip(badge, agg.activeCount + ' of ' + _engagementTotal + ' active now');
  } else {
    countEl.textContent = '';
    badge.className = 'badge empty footer-tooltip-target';
    _setFooterBadgeTooltip(badge, 'No active participants');
  }
}

function _renderEngagementPopover() {
  var el = document.getElementById('engagement-content');
  if (!el) return;
  var agg = _engagementAggregate();
  var views = Object.keys(agg.totals).sort(function(a, b) {
    return agg.totals[b].seconds - agg.totals[a].seconds;
  });
  var html = '<div class="slides-catalog-line" style="opacity:.85;font-weight:600;">'
    + '<span>Live: ' + agg.activeCount + ' of ' + _engagementTotal + ' active now</span></div>';
  if (!views.length) {
    html += '<div style="padding:6px;opacity:0.5">No activity yet</div>';
  } else {
    for (var i = 0; i < views.length; i++) {
      var v = views[i], t = agg.totals[v];
      var label = ENGAGEMENT_VIEW_LABELS[v] || v;
      var liveOnView = agg.activeByView[v] ? ' · ' + agg.activeByView[v] + ' now' : '';
      html += '<div class="slides-catalog-line">'
        + '<span class="slides-cache-title truncate">' + escHtml(label) + liveOnView + '</span>'
        + '<span class="slides-cache-label" style="color:var(--muted)">' + t.visits + 'v · ' + t.clicks + 'c</span>'
        + '<span class="slides-cache-detail">' + _fmtSecs(t.seconds) + '</span>'
        + '</div>';
    }
  }
  el.innerHTML = html;
}
```

- [ ] **Step 4: Register the hover + start the decay ticker**

In `static/host.js`, inside `_setupActivityLogHovers` (line 1010), after the existing `_makeHover('slides-log-hover', 'slides-log-popover', _renderSlidesLogPopover);` line (line 1021), add:

```javascript
  _makeHover('slides-log-hover', 'slides-log-popover', _renderSlidesLogPopover);
  _makeHover('engagement-hover', 'engagement-popover', _renderEngagementPopover);
  setInterval(renderEngagementBadge, 2000);
  renderEngagementBadge();
}
```

(The 2s ticker re-evaluates the freshness window so the badge decays to `👁` / `.empty` on its own when participants go idle, with no server push.)

- [ ] **Step 5: Verify in the browser (screenshot proof)**

With the daemon running and at least one participant page open and being interacted with:
1. Open the host page `http://localhost:8081/`.
2. Confirm the footer shows `👁 <N>` where N tracks the number of currently-active participants, and drops to `👁` (no number, muted) ~75s after the participant goes idle.
3. Hover the badge → popover shows `Live: N of M active now` and one row per view: `<Label> [· K now]   <Vv · Cc>   <time>`.
4. Take a screenshot of the badge + open popover (UI-change proof).
5. Confirm no Console errors.

- [ ] **Step 6: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat(engagement): host footer badge with live count + breakdown popover

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Documentation

**Files:**
- Modify: `ARCHITECTURE.md` (data-flow + the participant→daemon→host engagement path)
- Modify: `backlog.md` (feature entry)

- [ ] **Step 1: Update backlog.md**

Append an entry to `backlog.md`:

```markdown
- **Participant engagement tracking** — participant page accumulates per-view active time / visits / clicks (active = tab visible + interaction within 60s) and flushes deltas to `POST /api/participant/activity` (≤30s, plus on hide/unload). Daemon merges into `PersistedParticipant.engagement` (persisted) and stamps runtime `last_active_at`/`last_view`. Surfaced to the host on the existing `participant_list_updated` message; host shows a `👁 N active` footer badge (live count derived locally from `last_active_at`) with a cumulative per-view breakdown popover.
```

- [ ] **Step 2: Update ARCHITECTURE.md**

Add a short subsection (under the participant↔daemon interactions) describing the engagement flow: client `Engagement` module → `POST /api/participant/activity` → `ParticipantState.engagement` (persisted by the 3s snapshot loop) → `_build_host_participants_list` → `participant_list_updated` → host badge with locally-derived live pulse. Match the surrounding doc style; if C4/sequence diagrams exist for participant actions, add the activity report alongside the existing `register`/`vote` flows.

- [ ] **Step 3: Commit**

```bash
git add ARCHITECTURE.md backlog.md
git commit -m "docs(engagement): document participant engagement tracking flow

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Full verification, push, prod confirm

- [ ] **Step 1: Run the full daemon test suite**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/daemon --confcutdir=tests/daemon -q`
Expected: all pass (including the new engagement tests and the contract test).

- [ ] **Step 2: Run the project pre-push parity check**

Run: `arch -arm64 uv run --extra dev --extra daemon bash tests/check-all.sh`
Expected: green. Fix anything it flags before pushing.

- [ ] **Step 3: Push to master**

```bash
git fetch origin master -q && git rebase origin/master && git push origin master
```
Expected: push accepted. (Resolve conflicts if the other active session in this folder pushed meanwhile.)

- [ ] **Step 4: Confirm production deploy took effect**

Railway auto-deploys master in ~40-50s. After waiting, probe the new endpoint on prod (unauthenticated participant route) to confirm the deploy is live — e.g. a `POST` to `https://interact.victorrentea.ro/<session_id>/api/participant/activity` with an `X-Participant-ID` header and a tiny body should return `204` (or `400` only if the header is missing), not `404`. Confirm the host badge appears on the live host page.

- [ ] **Step 5: (Optional, stretch) Hermetic e2e**

If adding e2e coverage, write a Playwright scenario under `tests/docker/` driving a participant through several views and asserting the host badge/popover updates, then run it **in Docker** (`bash tests/docker/run-hermetic.sh -k <name>`). Do not mark this done unless it actually ran in Docker.

- [ ] **Step 6: Screenshot proof**

Attach the host-badge + popover screenshot from Task 8 Step 5 (and ideally a prod screenshot) as proof of the UI change.

---

## Self-Review

**Spec coverage:**
- Active/idle/visit/flush definitions → Task 7 (`Engagement` module: visibility + 60s idle + interaction listeners; 30s flush; keepalive on hide/unload; initial-view-not-a-visit via `isInitial`).
- Time + visits + clicks per view → Tasks 1, 4, 7 (model, merge, client accumulators).
- New REST endpoint contract → Task 4 (`ActivityReportRequest` / `ViewEngagementDelta`).
- Additive persistence in `PersistedParticipant.engagement` (backward-compatible) → Tasks 1–3.
- Host-derived live pulse from `last_active_at` (75s freshness, 2s ticker) → Tasks 4, 5, 8.
- Footer badge + cumulative breakdown popover, `.empty` at 0 (no "0") → Task 8.
- Piggyback on `participant_list_updated`, no new WS type/AsyncAPI change → Tasks 4, 5, 8.
- OpenAPI/API.md regen → Task 6. Docs → Task 9. Proof/verify/prod → Task 10.

**Placeholder scan:** none — every code/test step shows complete code; commands have expected output.

**Type/name consistency:** `engagement` dict shape `{view: {seconds, visits, clicks}}` is identical across `ViewEngagement` (Task 1), `ParticipantState.engagement` (Task 2), snapshot row (Task 3), handler merge (Task 4), host list (Task 5), and host JS (Task 8). `last_active_at` is epoch-ms float everywhere (daemon `time.time()*1000` ↔ host `Date.now()`). View id set is identical between client `Engagement` (implicit via `showView` names), daemon `_KNOWN_VIEWS`, and host `ENGAGEMENT_VIEW_LABELS`. Endpoint path `/api/participant/activity` matches client `fetch` path (minus the Railway-stripped `/{session_id}` prefix). Functions `_captureEngagement`, `renderEngagementBadge`, `_engagementAggregate`, `_renderEngagementPopover` are defined once and referenced consistently.
