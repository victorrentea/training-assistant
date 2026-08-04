# Host-Machine Auto Session Switch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the trainer's own machine, Interact jumps instantly to a newly started session and joins it as `Victor (trainer)` — with no way for any participant to obtain either the jump or the identity.

**Architecture:** The redirect reuses the already-public, already-loopback-only `GET /api/session/active`. The trainer identity is granted by a *second local call* to a new daemon endpoint deliberately placed outside `/api/participant/*`, the only prefix Railway forwards. Because the grant happens entirely over loopback, no secret ever travels through Railway, so there is nothing to intercept, replay, or expire.

**Tech Stack:** FastAPI + Pydantic (daemon), vanilla JS (`static/participant.html`), pytest, node test runner.

## Global Constraints

- All code, comments, and commit messages in English.
- Daemon REST contracts use strict Pydantic models — no raw dict payloads.
- Never edit `API.md` by hand; regenerate with `python3 scripts/generate_apis_md.py --output API.md`.
- CI runs only `tests/unit/ tests/core/ tests/openapi/ tests/features/slides/test_router.py` — new Python tests go in `tests/unit/`.
- Run tests with `arch -arm64 uv run --extra dev --extra daemon python -m pytest ...` (Apple Silicon).
- The reserved trainer name is exactly `Victor (trainer)`, held in one module constant.
- `participant_names_updated` MUST stay UUID-free (`daemon/ws_messages.py:60-67`). Do not add UUIDs to it.
- Commit after each task; push to `master` directly.

## File Structure

| File | Responsibility |
| --- | --- |
| `daemon/participant/state.py` (modify) | Owns `trainer_pids` — who has claimed trainer in this session |
| `daemon/participant/sanitize.py` (modify) | Owns the reserved-name constant and its normalized comparison |
| `daemon/participant/router.py` (modify) | Applies the gate at both name ingress points (`/register`, `/name`) |
| `daemon/host_machine/router.py` (create) | The loopback-only claim endpoint — one file, one responsibility |
| `daemon/host_server.py` (modify) | Mounts the new router |
| `daemon/leaderboard/router.py` (modify) | Carries `is_trainer` to every viewer |
| `static/participant.html` (modify) | Poll → redirect → fresh UUID → claim |
| `tests/unit/test_reserved_trainer_name.py` (create) | Gate behaviour |
| `tests/unit/test_host_machine_claim.py` (create) | Claim endpoint + order-independence |
| `tests/unit/test_privileged_route_prefixes.py` (create) | **The security invariant** |

---

### Task 1: Trainer claim set in participant state

**Files:**
- Modify: `daemon/participant/state.py:32-68` (`__init__`), `:163-184` (`snapshot`), `:199-225` (`reset`), `sync_from_restore`
- Test: `tests/unit/test_host_machine_claim.py`

**Interfaces:**
- Produces: `participant_state.trainer_pids: set[str]`, cleared by `reset()`, round-tripped by `snapshot()` / `sync_from_restore()` under key `"trainer_pids"`.

- [ ] **Step 1: Write the failing test**

```python
from daemon.participant.state import participant_state


def test_trainer_pids_round_trip_and_reset():
    participant_state.reset()
    participant_state.trainer_pids.add("uuid-a")

    assert participant_state.snapshot()["trainer_pids"] == ["uuid-a"]

    participant_state.reset()
    assert participant_state.trainer_pids == set()

    participant_state.sync_from_restore({"trainer_pids": ["uuid-b"]})
    assert participant_state.trainer_pids == {"uuid-b"}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -v`
Expected: FAIL — `AttributeError: 'ParticipantState' object has no attribute 'trainer_pids'`

- [ ] **Step 3: Add the field**

In `__init__`, next to `anonymous_pids`:

```python
        # UUIDs that proved they run on the trainer's machine by calling the
        # loopback-only claim endpoint. Persisted so the trainer keeps the
        # badge across a daemon restart within the same session.
        self.trainer_pids: set[str] = set()
```

In `snapshot()`, inside the returned dict:

```python
                "trainer_pids": sorted(self.trainer_pids),
```

In `reset()`, next to `self.anonymous_pids.clear()`:

```python
            self.trainer_pids.clear()
```

In `sync_from_restore`, follow the exact idiom already used for `anonymous_pids` in that method (`self.trainer_pids = set(data.get("trainer_pids", []))`).

- [ ] **Step 4: Run it and watch it pass**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/participant/state.py tests/unit/test_host_machine_claim.py
git commit -m "feat(participant): track which UUIDs claimed trainer on the host machine"
```

---

### Task 2: Reserved trainer name, enforced at both ingress points

Names enter through exactly two REST endpoints — `POST /api/participant/register` (`daemon/participant/router.py:605`) and `PUT`/`POST` `rename_participant` (`daemon/participant/router.py:713`). Both already funnel through `sanitize_name`. Gate both, or the gate is decorative.

**Files:**
- Modify: `daemon/participant/sanitize.py` (add constant + predicate)
- Modify: `daemon/participant/router.py:605-700` (register), `:713-746` (rename)
- Test: `tests/unit/test_reserved_trainer_name.py`

**Interfaces:**
- Consumes: `participant_state.trainer_pids` (Task 1)
- Produces: `RESERVED_TRAINER_NAME: str`, `is_reserved_trainer_name(name: str | None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
from daemon.participant.sanitize import RESERVED_TRAINER_NAME, is_reserved_trainer_name


def test_reserved_name_matches_regardless_of_case_and_spacing():
    assert is_reserved_trainer_name(RESERVED_TRAINER_NAME)
    assert is_reserved_trainer_name("  victor   (TRAINER) ")
    assert not is_reserved_trainer_name("Victor")
    assert not is_reserved_trainer_name(None)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_reserved_trainer_name.py -v`
Expected: FAIL — `ImportError: cannot import name 'RESERVED_TRAINER_NAME'`

- [ ] **Step 3: Implement in `daemon/participant/sanitize.py`**

`normalize_for_dedup` already exists in this module (`daemon/participant/sanitize.py:72`) — reuse it rather than writing a second normalizer.

```python
# The trainer's display name is a privilege, not a string anyone may type.
# Only a UUID that claimed trainer over loopback may hold it.
RESERVED_TRAINER_NAME = "Victor (trainer)"


def is_reserved_trainer_name(name: str | None) -> bool:
    """True if `name` collides with the reserved trainer name after normalization."""
    if not name:
        return False
    return normalize_for_dedup(name) == normalize_for_dedup(RESERVED_TRAINER_NAME)
```

- [ ] **Step 4: Write the failing endpoint tests**

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.participant.router import router
from daemon.participant.sanitize import RESERVED_TRAINER_NAME
from daemon.participant.state import participant_state

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    participant_state.reset()
    yield
    participant_state.reset()


def test_impostor_cannot_register_under_the_reserved_name():
    r = client.post(
        "/api/participant/register",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "impostor"},
    )
    assert r.status_code == 403
    assert participant_state.participant_names.get("impostor") != RESERVED_TRAINER_NAME


def test_impostor_cannot_rename_into_the_reserved_name():
    client.post(
        "/api/participant/register",
        json={"name": "Ordinary"},
        headers={"X-Participant-ID": "impostor"},
    )
    r = client.post(
        "/api/participant/name",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "impostor"},
    )
    assert r.status_code == 403
    assert participant_state.participant_names["impostor"] == "Ordinary"


def test_claimed_trainer_may_hold_the_reserved_name():
    participant_state.trainer_pids.add("trainer")
    r = client.post(
        "/api/participant/register",
        json={"name": RESERVED_TRAINER_NAME},
        headers={"X-Participant-ID": "trainer"},
    )
    assert r.status_code == 200
    assert participant_state.participant_names["trainer"] == RESERVED_TRAINER_NAME
```

**Before running:** confirm the rename route's actual path and method by reading the decorator directly above `async def rename_participant` in `daemon/participant/router.py:712`, and use that exact path in the test.

- [ ] **Step 5: Run and watch them fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_reserved_trainer_name.py -v`
Expected: FAIL — impostor registrations currently succeed with a 200.

- [ ] **Step 6: Add the gate to both endpoints**

In `register_participant`, immediately after `explicit_name = sanitize_name(body.name)`:

```python
    if is_reserved_trainer_name(explicit_name) and pid not in ps.trainer_pids:
        return JSONResponse({"error": "Name is reserved"}, status_code=403)
```

In `rename_participant`, immediately after the `if not raw_name:` guard:

```python
    if is_reserved_trainer_name(raw_name) and pid not in ps.trainer_pids:
        return JSONResponse({"error": "Name is reserved"}, status_code=403)
```

Add `is_reserved_trainer_name` to the existing `from daemon.participant.sanitize import ...` line.

- [ ] **Step 7: Run and watch them pass**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_reserved_trainer_name.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add daemon/participant/sanitize.py daemon/participant/router.py tests/unit/test_reserved_trainer_name.py
git commit -m "feat(participant): reserve the trainer display name for claimed UUIDs"
```

---

### Task 3: The loopback-only claim endpoint

**Files:**
- Create: `daemon/host_machine/__init__.py` (empty), `daemon/host_machine/router.py`
- Modify: `daemon/host_server.py:287-289` (mount, next to `session_public_router`)
- Test: `tests/unit/test_host_machine_claim.py` (extend from Task 1)

**Interfaces:**
- Consumes: `participant_state.trainer_pids` (Task 1), `RESERVED_TRAINER_NAME` (Task 2)
- Produces: `host_machine_router: APIRouter` serving `POST /api/host-machine/claim-trainer`, request `ClaimTrainerRequest(participant_id: str)`, response `ClaimTrainerResponse(granted: bool, display_name: str)`

The endpoint needs no authentication of its own. Its security comes entirely from being reachable only over loopback: `uvicorn` binds `127.0.0.1` (`daemon/host_server.py:359`), `_local_access_guard` rejects non-loopback `Host` headers (`daemon/host_server.py:158`), CORS admits only `https://interact.victorrentea.ro` (`daemon/host_server.py:151`), and Railway forwards nothing outside `/api/participant/*`. Say this in a comment at the top of the file so nobody later "hardens" it by adding a token that would then have to travel through Railway.

- [ ] **Step 1: Write the failing test (including order-independence)**

```python
def test_claim_then_register_yields_the_trainer_name():
    participant_state.reset()
    claim_client.post("/api/host-machine/claim-trainer", json={"participant_id": "t1"})
    r = participant_client.post(
        "/api/participant/register", json={}, headers={"X-Participant-ID": "t1"}
    )
    assert r.json()["name"] == RESERVED_TRAINER_NAME


def test_register_then_claim_also_yields_the_trainer_name():
    participant_state.reset()
    participant_client.post(
        "/api/participant/register", json={"name": "Ordinary"},
        headers={"X-Participant-ID": "t2"},
    )
    r = claim_client.post("/api/host-machine/claim-trainer", json={"participant_id": "t2"})
    assert r.json() == {"granted": True, "display_name": RESERVED_TRAINER_NAME}
    assert participant_state.participant_names["t2"] == RESERVED_TRAINER_NAME
```

Build `claim_client` and `participant_client` with the same `FastAPI() + include_router + TestClient` pattern used in `tests/unit/test_inbox_router.py:14-16`.

- [ ] **Step 2: Run and watch it fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Implement `daemon/host_machine/router.py`**

```python
"""Host-machine privilege endpoints — reachable only over loopback.

This router is deliberately NOT under /api/participant/*. That prefix is the
only one Railway forwards to the daemon (railway/features/ws/proxy_bridge.py),
so everything here is unreachable from the internet by construction. That is
the whole security model: no token travels through Railway, so there is nothing
to intercept or replay. Do not "harden" this with a shared secret — moving the
grant onto a network-visible path is what would weaken it.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from daemon.participant.sanitize import RESERVED_TRAINER_NAME
from daemon.participant.state import participant_state

router = APIRouter(prefix="/api/host-machine", tags=["host-machine"])


class ClaimTrainerRequest(BaseModel):
    participant_id: str


class ClaimTrainerResponse(BaseModel):
    granted: bool
    display_name: str


@router.post("/claim-trainer", response_model=ClaimTrainerResponse)
async def claim_trainer(body: ClaimTrainerRequest) -> ClaimTrainerResponse:
    """Grant trainer identity to a UUID running on this machine.

    Registration arrives over a different path (browser -> Railway -> WS ->
    daemon), so claim and register race. Both orders must work: this handler
    renames an already-registered UUID, and register consults trainer_pids for
    a UUID that claimed first.
    """
    ps = participant_state
    ps.trainer_pids.add(body.participant_id)
    if body.participant_id in ps.participant_names:
        ps.participant_names[body.participant_id] = RESERVED_TRAINER_NAME
        ps.anonymous_pids.discard(body.participant_id)
    ps.persist()
    return ClaimTrainerResponse(granted=True, display_name=RESERVED_TRAINER_NAME)
```

- [ ] **Step 4: Make register honour a prior claim**

In `register_participant`, in the "New participant — assign identity" section, before the `if explicit_name:` branch:

```python
    if pid in ps.trainer_pids:
        # Claimed trainer: identity is fixed, never auto-assigned or typed.
        ps.anonymous_pids.discard(pid)
        explicit_name = RESERVED_TRAINER_NAME
```

Also make the returning-participant early-return honour it, so a trainer who claims after registering does not get their old name echoed back.

- [ ] **Step 5: Mount the router**

In `daemon/host_server.py`, beside the existing `session_public_router` mount at line 287:

```python
    from daemon.host_machine.router import router as host_machine_router
    app.include_router(host_machine_router)   # /api/host-machine/* (loopback only)
```

- [ ] **Step 6: Notify the host roster**

After a successful claim that renamed an existing participant, call `_notify_host_participant_list()` the same way `rename_participant` does (`daemon/participant/router.py:744`), so the host screen updates without a refresh. Import it from `daemon.participant.router`.

- [ ] **Step 7: Run and watch them pass**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add daemon/host_machine/ daemon/host_server.py daemon/participant/router.py tests/unit/test_host_machine_claim.py
git commit -m "feat(host-machine): grant trainer identity over loopback only"
```

---

### Task 4: The security invariant, as a test

This is the single most valuable test in the plan. It fails if a future refactor moves a privileged route under the one prefix Railway forwards.

**Files:**
- Create: `tests/unit/test_privileged_route_prefixes.py`

- [ ] **Step 1: Write the test**

```python
"""A privileged route under /api/participant/* would be world-reachable.

railway/features/ws/proxy_bridge.py forwards /api/participant/{path:path} to
the daemon. Anything mounted there is on the public internet. The host-machine
router grants trainer identity with no authentication because it is loopback
only — if it ever moved under that prefix, any participant could claim it.
"""
from daemon.host_machine.router import router as host_machine_router

PUBLICLY_FORWARDED_PREFIX = "/api/participant"


def test_host_machine_routes_are_not_publicly_forwarded():
    offenders = [
        route.path
        for route in host_machine_router.routes
        if route.path.startswith(PUBLICLY_FORWARDED_PREFIX)
    ]
    assert offenders == [], (
        f"Privileged host-machine routes exposed via Railway: {offenders}"
    )


def test_claim_trainer_is_actually_mounted_where_we_think():
    paths = {route.path for route in host_machine_router.routes}
    assert "/api/host-machine/claim-trainer" in paths
```

- [ ] **Step 2: Run it**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_privileged_route_prefixes.py -v`
Expected: PASS (2 passed) — it guards an invariant Task 3 already satisfies.

- [ ] **Step 3: Prove it can fail**

Temporarily change the router prefix in `daemon/host_machine/router.py` to `/api/participant/host-machine`, re-run, and confirm `test_host_machine_routes_are_not_publicly_forwarded` FAILS. Revert. A guard nobody has seen fail is not a guard.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_privileged_route_prefixes.py
git commit -m "test: privileged routes must stay off the Railway-forwarded prefix"
```

---

### Task 5: Trainer badge on the leaderboard

The leaderboard is where every participant sees names, so it is where the badge belongs. It renders from the server-side flag, never from the name string. `participant_names_updated` stays untouched and UUID-free.

**Files:**
- Modify: `daemon/leaderboard/router.py:18-26` (`LeaderboardPosition`), `:35-45` (entry construction)
- Test: `tests/unit/test_host_machine_claim.py`

**Interfaces:**
- Produces: `LeaderboardPosition.is_trainer: bool = False`

- [ ] **Step 1: Write the failing test**

```python
def test_leaderboard_marks_the_claimed_trainer():
    participant_state.reset()
    participant_state.trainer_pids.add("t1")
    participant_state.participant_names["t1"] = RESERVED_TRAINER_NAME
    participant_state.participant_names["p2"] = "Ordinary"
    participant_state.scores.update({"t1": 5, "p2": 3})

    entries = leaderboard_client.post("/api/s1/host/leaderboard/show").json()["entries"]
    by_name = {e["name"]: e["is_trainer"] for e in entries}
    assert by_name[RESERVED_TRAINER_NAME] is True
    assert by_name["Ordinary"] is False
```

- [ ] **Step 2: Run and watch it fail**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -k leaderboard -v`
Expected: FAIL — `KeyError: 'is_trainer'`

- [ ] **Step 3: Add the field and populate it**

```python
class LeaderboardPosition(BaseModel):
    rank: int
    name: str
    score: int
    avatar: str | None = None
    letter: str | None = None
    color: str | None = None
    universe: str | None = None
    # Server-side truth, never inferred from the display string.
    is_trainer: bool = False
```

In `show_leaderboard`, set `is_trainer=pid in participant_state.trainer_pids` while building each entry, using the pid already in scope from the scores snapshot.

- [ ] **Step 4: Run and watch it pass**

Run: `arch -arm64 uv run --extra dev --extra daemon python -m pytest tests/unit/test_host_machine_claim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/leaderboard/router.py tests/unit/test_host_machine_claim.py
git commit -m "feat(leaderboard): carry a server-side trainer flag"
```

---

### Task 6: Frontend — poll, redirect, fresh UUID, claim

**Files:**
- Modify: `static/participant.html:2949-2954` (UUID minting), plus a new polling block
- Reference: `static/landing.html:479-520` — the existing poll to mirror
- Test: `tests/test_participant_js.js`

**Interfaces:**
- Consumes: `GET http://localhost:1234/api/session/active` → `{session_id}`; `POST http://127.0.0.1:1234/api/host-machine/claim-trainer` → `{granted, display_name}`

- [ ] **Step 1: Write the failing JS test**

Follow the existing style in `tests/test_participant_js.js`. Assert three behaviours: (a) with no `ON_HOST_MACHINE` cookie no fetch to `localhost:1234` is made at all; (b) when the daemon reports a session id equal to the current one, `location.href` is not assigned; (c) when it reports a different id, the stored UUID key `workshop_participant_uuid` is removed *before* navigation.

- [ ] **Step 2: Run and watch it fail**

Run: `node tests/test_participant_js.js`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the poll**

```javascript
// ── Host-machine auto session switch ────────────────────────────────────────
// Mirrors the landing-page poll (static/landing.html). The ON_HOST_MACHINE
// cookie is NOT a security gate — it is JS-readable and anyone can set it. It
// only keeps participants' browsers from firing pointless requests at their
// own localhost. The real boundary is that only a browser on the trainer's
// machine can reach the trainer's 127.0.0.1:1234 at all.
var HOST_MACHINE_POLL_MS = 1000;

function _onHostMachine() {
  return document.cookie.split(';').some(function (p) {
    return p.trim() === 'ON_HOST_MACHINE=true';
  });
}

async function _pollForNewSession() {
  if (!_onHostMachine()) return;
  try {
    var r = await fetch('http://localhost:1234/api/session/active',
                        { signal: AbortSignal.timeout(800) });
    if (!r.ok) return;
    var active = (await r.json()).session_id;
    if (!active || active === _sessionId) return;
    // Fresh session => fresh identity: drop the UUID so the next page load
    // mints a new one and the trainer starts with a clean leaderboard.
    localStorage.removeItem('workshop_participant_uuid');
    window.location.href = '/' + active + '/';
  } catch (e) {
    // Daemon absent or unreachable: this is every participant's normal case.
  }
}

if (_onHostMachine()) setInterval(_pollForNewSession, HOST_MACHINE_POLL_MS);
```

Use whatever variable already holds the current session id in `participant.html` in place of `_sessionId` — read it from the file rather than assuming the name.

- [ ] **Step 4: Claim trainer right after minting the UUID**

Immediately after the `_myUUID` IIFE at `static/participant.html:2950-2954`, and before registration runs:

```javascript
// On the trainer's machine, claim the trainer identity over loopback. This is
// the ONLY thing that may grant the reserved name; it never travels through
// Railway, so there is no token to intercept.
if (_onHostMachine()) {
  fetch('http://127.0.0.1:1234/api/host-machine/claim-trainer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participant_id: _myUUID }),
    signal: AbortSignal.timeout(800),
  }).catch(function () { /* not on the host machine — stay an ordinary participant */ });
}
```

- [ ] **Step 5: Run and watch them pass**

Run: `node tests/test_participant_js.js`
Expected: all pass, including the 18 pre-existing.

- [ ] **Step 6: Commit**

```bash
git add static/participant.html tests/test_participant_js.js
git commit -m "feat(participant): auto-switch to the new session on the host machine"
```

---

### Task 7: Regenerate contracts and run the full local gate

**Files:**
- Modify: `openapi.json`, `API.md`

- [ ] **Step 1: Regenerate**

```bash
arch -arm64 uv run --extra dev --extra daemon python -c "from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
arch -arm64 uv run --extra dev --extra daemon python3 scripts/generate_apis_md.py --output API.md
```

- [ ] **Step 2: Run the hook-parity gate**

Run: `arch -arm64 uv run --extra dev --extra daemon bash tests/check-all.sh`
Expected: green. Fix anything red before continuing — do not proceed on a red gate.

- [ ] **Step 3: Run the hermetic e2e suite**

Run: `bash tests/docker/run-hermetic.sh`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add openapi.json API.md
git commit -m "chore(api): regenerate contracts for the host-machine claim endpoint"
```

---

### Task 8: Adversarial penetration test

Explicitly requested, and the acceptance gate for the whole feature.

- [ ] **Step 1: Dispatch an adversarial subagent**

Brief it to play an ordinary participant in a headless browser inside Docker, with **no route to the host's port 1234**, and to attempt:

1. Reaching `claim-trainer` through `https://interact.victorrentea.ro` by any path shape — including `/api/participant/../host-machine/claim-trainer`, encoded traversal, and the slides routes.
2. Obtaining the trainer's session code by any channel: enumeration against the rate limiter, `/api/status`, `/api/is-active-session`, the ended-session view, slides links, WS frames.
3. Holding the reserved name via `/register`, via rename, and with case/whitespace/Unicode variants (`victor (trainer)`, `Victor  (trainer)`, NBSP, homoglyphs).
4. Pointing its own local daemon at port 1234 to see whether a self-hosted response grants anything beyond self-deception.

- [ ] **Step 2: Triage findings honestly**

Anything that succeeds is a blocker. Report it with the exact request that worked. Do not downgrade a finding to "unlikely".

- [ ] **Step 3: Fix, re-run, and only then declare the feature done**

---

## Self-Review

**Spec coverage:** redirect → Task 6; loopback claim endpoint → Task 3; order-independence → Task 3 Steps 1/4; new UUID per session → Task 6 Step 3; cookie demoted to a hint → Task 6 comment; badge from server flag → Task 5; reserved name at both ingress points → Task 2; security regression test → Task 4; pentest → Task 8; contract regeneration → Task 7.

**Known gap, deliberately left to the implementer:** the exact variable holding the current session id in `participant.html` and the exact rename route path must be read from the source rather than assumed; both are called out inline where they are needed.

**Type consistency:** `trainer_pids` (set[str]) is used identically in Tasks 1, 2, 3, 5. `RESERVED_TRAINER_NAME` and `is_reserved_trainer_name` keep the same names in Tasks 2, 3, 5. `ClaimTrainerRequest.participant_id` matches the JSON body sent in Task 6.
