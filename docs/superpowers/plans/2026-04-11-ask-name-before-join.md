# Ask Name Before Join Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require explicit participant identity selection before join, while preserving rejoin by UUID and host-machine-only local fallback behavior.

**Architecture:** Identity resolution is split into two APIs: lookup-only `/rejoin` and create-or-return `/register`. Participant frontend adds a pre-join gate and delays websocket connection until identity is resolved. Landing controls host-machine-only local probing via explicit cookie toggle.

**Tech Stack:** FastAPI (daemon + Railway proxy), vanilla JS/HTML/CSS frontend, pytest + hermetic docker e2e.

---

### Task 1: Daemon participant identity endpoints

**Files:**
- Modify: `daemon/participant/router.py`
- Modify: `tests/daemon/test_participant_router.py`

- [ ] Add failing tests for `/rejoin`, `/register {name}`, duplicate-name `409`, and unchanged identity on returning UUID.
- [ ] Implement `/rejoin` as lookup-only endpoint.
- [ ] Implement optional `name` request model for `/register` with duplicate rejection and explicit-name create path.
- [ ] Verify targeted daemon tests pass.

### Task 2: Participant pre-join frontend flow

**Files:**
- Modify: `static/participant.html`
- Modify: `static/participant.css`
- Modify: `static/participant.js`
- Modify: frontend test files that assert join behavior

- [ ] Add failing frontend/unit/integration tests for pre-join gate behavior.
- [ ] Add pre-join UI with manual-name and random buttons.
- [ ] Refactor join bootstrap to use `/rejoin` first for existing UUID.
- [ ] Connect websocket only after successful identity resolution.
- [ ] Remove post-join onboarding "name set" tracking.
- [ ] Verify frontend syntax and targeted tests pass.

### Task 3: Landing ON_HOST_MACHINE toggle and guarded localhost probing

**Files:**
- Modify: `static/landing.html`
- Modify: tests covering landing behavior

- [ ] Add checkbox UI pinned to left-bottom and cookie persistence (`ON_HOST_MACHINE`).
- [ ] Gate localhost `/api/session/active` polling behind cookie.
- [ ] Keep default behavior with no localhost probing unless explicitly enabled.
- [ ] Verify targeted landing/session tests pass.

### Task 4: Local testing fallback name retry

**Files:**
- Modify: `static/participant.js`
- Modify: participant/e2e tests

- [ ] Add candidate-name retry loop (` (local)` + `+`) when explicit register returns `409`.
- [ ] Ensure retry path is used only in host-machine testing flow.
- [ ] Add coverage for suffix retry behavior.

### Task 5: E2E and hermetic migration

**Files:**
- Modify: `tests/pages/participant_page.py`
- Modify: affected `tests/features/**` and `tests/docker/**`

- [ ] Update helper methods for default random pre-join path.
- [ ] Keep most test flows simple by joining through random button.
- [ ] Add focused coverage for manual-name and duplicate-name error handling.
- [ ] Run hermetic suite and capture proof output.

### Task 6: Documentation and completion

**Files:**
- Modify: `backlog.md`
- Modify: `tasks/todo.md`
- Modify: generated API docs if contracts changed (`docs/openapi.yaml`, `API.md`)

- [ ] Mark GH#110 done in backlog and review notes.
- [ ] Regenerate API docs if OpenAPI contract changed.
- [ ] Run final verification commands before commit/push.
