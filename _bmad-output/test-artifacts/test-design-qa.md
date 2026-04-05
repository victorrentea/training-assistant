---
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
lastSaved: '2026-03-28'
workflowType: 'testarch-test-design'
inputDocuments:
  - CLAUDE.md (PRD + ADR + tech spec)
  - tests/ (full suite analysis - 546 tests, 45 files)
---

# Test Design for QA: Training Assistant — Live Workshop Interaction Tool

**Purpose:** Test execution recipe. Defines what to test, how to test it, and what's missing from the existing 546-test suite.

**Date:** 2026-03-28
**Author:** Murat (TEA Agent)
**Status:** Draft
**Project:** training-assistant

**Related:** See Architecture doc (test-design-architecture.md) for testability concerns and R-01 blocker.

---

## Executive Summary

**Scope:** System-level test coverage assessment and gap analysis for all features: polls, Q&A, word cloud, code review, debate, leaderboard, quiz, session management, and training daemon.

**Risk Summary:**
- Total Risks: 10 (1 high-priority score >=6, 5 medium, 4 low)
- Critical Category: DATA (concurrent state mutation without locking)

**Coverage Summary:**
- P0 tests: ~8 (critical paths, concurrency, security)
- P1 tests: ~12 (core features, race conditions, daemon integration)
- P2 tests: ~8 (secondary features, edge cases)
- P3 tests: ~3 (nice-to-have, exploratory)
- **Total**: ~31 scenarios (~18-29 hours new test development)

**Existing coverage:** 546 tests already exist. **Only ~13 new tests needed** to close critical gaps.

---

## Not in Scope

| Item | Reasoning | Mitigation |
|------|-----------|------------|
| **Desktop overlay (Swift/AppKit)** | Different platform (macOS native), different language | Manual testing by project owner |
| **Wispr addons (macOS daemon)** | Separate codebase, macOS-specific hardware integration | Manual testing by project owner |
| **Claude API response quality** | LLM output quality is non-deterministic | Mocked responses in tests; manual spot-checks |
| **Railway deployment infrastructure** | Platform managed by Railway | Deployment monitor (watch-deploy.sh) provides alerting |
| **Browser compatibility (Safari, Firefox)** | Chromium-only E2E tests | Acceptable — workshop participants use modern browsers |

---

## Dependencies & Test Blockers

### Backend Dependencies (Pre-Implementation)

1. **R-01: asyncio.Lock on state mutations** — Backend Dev — Before load testing
   - QA needs concurrent state access to be thread-safe
   - Without this, load test P0-006 will produce non-deterministic failures

### QA Infrastructure (Already In Place)

1. **Test Server Fixture** — conftest.py
   - Real uvicorn on free port, auto-discovery
   - Coverage.py integration via `_E2E_COVERAGE=1`

2. **Page Objects** — tests/pages/
   - `HostPage`: poll CRUD, activity management, participant monitoring
   - `ParticipantPage`: join, vote, submit Q&A, debate, code review

3. **Cleanup Fixtures** — conftest.py
   - `clean_qa`, `clean_codereview`, `clean_wordcloud`, `clean_scores`, `clean_all`

4. **Test Data** — No external data dependencies
   - State created via WS messages and API calls within each test
   - In-memory state resets per server instance

---

## Risk Assessment

### High-Priority Risks (Score >= 6)

| Risk ID | Category | Description | Score | QA Test Coverage |
|---------|----------|-------------|-------|------------------|
| **R-01** | DATA | Concurrent state mutations without asyncio.Lock | **6** | P0-006: Load test with 50+ concurrent voters validates no data corruption |

### Medium-Priority Risks (Score 3-5)

| Risk ID | Category | Description | Score | QA Test Coverage |
|---------|----------|-------------|-------|------------------|
| R-02 | TECH | WebSocket reconnect loses in-flight messages | 4 | P0-004: Reconnect preserves name + score |
| R-03 | BUS | Speed-based scoring accuracy under concurrent load | 4 | P0-003, P0-007: Multi-select scoring + algorithm unit test |
| R-04 | TECH | Debate auto-assign race on concurrent side picks | 4 | P1-007: Concurrent WS debate side selection |
| R-05 | OPS | Daemon crash loses queued AI requests | 4 | P1-008: Daemon reconnect + request recovery |

### Low-Priority Risks

| Risk ID | Category | Description | Score | QA Test Coverage |
|---------|----------|-------------|-------|------------------|
| R-06 | SEC | WS auth via header only | 2 | P0-005: Auth boundary test |
| R-07 | PERF | Broadcast O(N) per mutation | 2 | P0-006: Load test at 150 connections |
| R-08 | BUS | Leaderboard score inconsistency | 2 | P1-005: Leaderboard reveal accuracy |

---

## Entry Criteria

- [x] Test environments provisioned (local uvicorn on free port)
- [x] Test data approach defined (in-memory, WS-seeded)
- [x] Page objects implemented (HostPage, ParticipantPage)
- [x] Cleanup fixtures ready (clean_qa, clean_all, etc.)
- [ ] R-01 (asyncio.Lock) resolved — **blocker for P0-006 load test**

## Exit Criteria

- [ ] All P0 tests passing (8 tests, 100% pass rate)
- [ ] All P1 tests passing (>= 95% pass rate)
- [ ] No flaky tests in P0 suite
- [ ] Load test validates 50+ concurrent participants without data corruption
- [ ] No open high-severity bugs

---

## Test Coverage Plan

**IMPORTANT:** P0/P1/P2/P3 = **priority and risk level**, NOT execution timing. All tests run on every PR.

### P0 (Critical)

**Criteria:** Blocks core functionality + High risk (>=6) + No workaround + Affects all participants

| Test ID | Requirement | Test Level | Risk Link | Status | Notes |
|---------|-------------|------------|-----------|--------|-------|
| **P0-001** | Participant joins, sets name, appears in host panel | E2E | R-02 | EXISTS | tests/e2e/test_join.py |
| **P0-002** | Single-select poll: create, vote, see results live | E2E | R-03 | EXISTS | tests/features/poll/ |
| **P0-003** | Multi-select poll: vote, correct reveal, speed scoring | E2E | R-03 | EXISTS | tests/features/poll/ |
| **P0-004** | WebSocket reconnect preserves name + score | E2E | R-02 | PARTIAL | Strengthen: verify score persistence across reconnect |
| **P0-005** | Host auth protects all admin endpoints (401 without creds) | API | R-06 | EXISTS | tests/unit/test_auth.py |
| **P0-006** | Concurrent voting under load (50+ participants) | Load | R-01, R-07 | **NEW** | Validates no vote count corruption under concurrent WS messages |
| **P0-007** | Speed-based scoring algorithm: correct point calculation | Unit | R-03 | **NEW** | Extract and unit-test scoring formula (currently only E2E tested) |
| **P0-008** | Activity switch guards (can't start poll during debate) | API | — | **NEW** | POST /api/poll returns 409 when debate active |

**Total P0: ~8 tests** (5 exist, 3 new)

---

### P1 (High)

**Criteria:** Important features + Medium risk + Common workflows

| Test ID | Requirement | Test Level | Risk Link | Status | Notes |
|---------|-------------|------------|-----------|--------|-------|
| **P1-001** | Q&A: submit, upvote, host moderation (edit/delete/answer) | E2E | — | EXISTS | tests/features/qa/ |
| **P1-002** | Word cloud: submit, topic set, clear | E2E | — | EXISTS | tests/features/wordcloud/ |
| **P1-003** | Code review: paste, select lines, confirm, scoring | E2E | — | EXISTS | tests/features/codereview/ |
| **P1-004** | Debate full lifecycle: sides, arguments, AI cleanup, prep, live | E2E | R-04 | EXISTS | tests/features/debate/ |
| **P1-005** | Leaderboard: top-5 dramatic reveal, personal rank | E2E | R-08 | EXISTS | tests/features/leaderboard/ |
| **P1-006** | Conference mode: auto-assigned names, avatars, rename | E2E | — | EXISTS | tests/e2e/ |
| **P1-007** | Concurrent debate side selection + auto-assign correctness | API/WS | R-04 | **NEW** | Two clients pick sides simultaneously; verify balanced auto-assign |
| **P1-008** | Daemon heartbeat detection + WS reconnect | Integration | R-05 | PARTIAL | Strengthen: verify quiz/debate requests survive daemon restart |
| **P1-009** | Session pause/resume: participants blocked then restored | E2E | — | EXISTS | tests/e2e/ |
| **P1-010** | Slides follow-trainer on participant page | E2E | — | **NEW** | Complex async promise queue logic |
| **P1-011** | Quiz generation via daemon (mocked LLM) | Integration | R-05 | EXISTS | tests/daemon/quiz/ |
| **P1-012** | Poll timer: countdown, expiry, auto-close | E2E | — | EXISTS | tests/features/poll/ |

**Total P1: ~12 tests** (9 exist, 3 new/strengthen)

---

### P2 (Medium)

**Criteria:** Secondary features + Low risk + Edge cases

| Test ID | Requirement | Test Level | Status | Notes |
|---------|-------------|------------|--------|-------|
| **P2-001** | Emoji reactions (participant to overlay/host) | E2E | EXISTS | tests/e2e/ |
| **P2-002** | Paste text submission + dismissal (max 10, 100KB limit) | API | **NEW** | Boundary validation |
| **P2-003** | File upload enforcement (size limit, count limit) | API | **NEW** | Boundary validation |
| **P2-004** | Version age display + auto-reload on deploy | E2E | EXISTS | tests/e2e/ |
| **P2-005** | Summary key points on notes page | E2E | PARTIAL | Read-only display test |
| **P2-006** | OpenAPI contract validation | Contract | EXISTS | tests/openapi/ |
| **P2-007** | Prometheus metrics endpoint | API | EXISTS | tests/core/ |
| **P2-008** | Transcript normalization accuracy | Unit | EXISTS | tests/daemon/transcript/ |

**Total P2: ~8 tests** (6 exist, 2 new)

---

### P3 (Low)

**Criteria:** Nice-to-have + Exploratory + Benchmarks

| Test ID | Requirement | Test Level | Status | Notes |
|---------|-------------|------------|--------|-------|
| **P3-001** | Smart paste LLM code extraction (mock Claude) | Integration | **NEW** | Mock Claude response, verify code extraction |
| **P3-002** | Desktop overlay integration | Manual | — | Different platform |
| **P3-003** | Wispr addons behavior | Manual | — | Different codebase |

**Total P3: ~3 tests** (1 new, 2 manual)

---

## Execution Strategy

**Philosophy:** Everything runs on every PR. The test suite is fast enough (<5 min) to run all tests without tiering.

### Every PR: pytest (~2-5 min)

**All functional tests** (P0 through P3):
- Unit tests (21 existing + 2 new)
- Integration/daemon tests (297 existing)
- E2E browser tests (221 existing + ~5 new) via Playwright
- Contract test (1 existing)
- Total: ~560 tests

**Why run in PRs:** Suite completes in under 5 minutes with Playwright parallelization

### Nightly: Load Tests (~10 min)

**Concurrent WebSocket tests:**
- P0-006: 50-150 concurrent participants, interleaved votes
- Existing load test: 30-300 connections

**Why defer to nightly:** Requires sustained concurrent connections; resource-intensive

### Manual: Ad Hoc

- Desktop overlay (macOS native)
- Wispr addons (macOS daemon)
- Visual spot-checks after UI changes

---

## QA Effort Estimate

| Priority | New Tests | Effort Range | Notes |
|----------|-----------|-------------|-------|
| P0 | 3 | ~8-12 hours | Load test setup, scoring unit test, activity guard API test |
| P1 | 3 | ~6-10 hours | Concurrent debate WS test, daemon reconnect, slides follow |
| P2 | 2 | ~3-5 hours | Paste/upload boundary validation (API level) |
| P3 | 1 | ~1-2 hours | Smart paste mock test |
| **Total** | **9 new + 4 strengthened** | **~18-29 hours** | **1 engineer** |

**Assumptions:**
- Excludes R-01 fix (asyncio.Lock) — that's backend dev work
- Includes test design, implementation, debugging, CI integration
- Assumes existing fixtures and page objects are reusable (they are)
- Excludes ongoing maintenance (~10% effort)

---

## Interworking & Regression

**Services and components impacted by any feature change:**

| Service/Component | Impact | Regression Scope | Validation Steps |
|-------------------|--------|-----------------|-----------------|
| **WebSocket hub** | All features route through WS | All E2E tests | Full test suite must pass |
| **State (AppState)** | Shared state across all features | All tests that modify state | Clean fixtures isolate state |
| **Scoring system** | Poll, Q&A, debate, code review all award points | Scoring tests in each feature | Verify score deltas match expected values |
| **Activity singleton** | Only one activity at a time | Activity switch tests | P0-008 validates guards |
| **Daemon integration** | Quiz, debate AI, summary, slides | Daemon test suite (297 tests) | Run daemon tests after any daemon/ change |

**Regression test strategy:**
- Full test suite runs on every PR — no selective testing needed at current suite size
- Daemon changes: verify quiz generation, debate AI cleanup, and summary paths
- Frontend changes: E2E tests cover participant and host flows end-to-end

---

## Appendix A: Priority-Based Test Execution

```bash
# Run all tests (default, every PR)
pytest

# Run only E2E tests
pytest tests/e2e tests/features

# Run only daemon tests
pytest tests/daemon

# Run only unit tests
pytest tests/unit

# Run load tests (nightly)
pytest tests/load -v -s

# Run with coverage
_E2E_COVERAGE=1 pytest --cov=. --cov-report=html

# Run tests marked for production validation
pytest -m prod
```

---

## Appendix B: Recommended New Test Implementations

### P0-006: Concurrent Voting Load Test

```python
# tests/load/test_concurrent_voting.py
@pytest.mark.load
async def test_concurrent_voting_no_corruption(server_url):
    """50+ participants vote simultaneously; verify vote counts sum correctly."""
    # 1. Create poll via API
    # 2. Connect 50 WS clients, set names
    # 3. All clients send 'vote' message for random options simultaneously
    # 4. Collect vote_update messages
    # 5. Assert: sum(vote_counts.values()) == 50
    # 6. Assert: no participant voted twice
```

### P0-007: Speed-Based Scoring Unit Test

```python
# tests/unit/test_scoring.py
def test_speed_scoring_linear_decay():
    """Fastest voter gets 1000 pts, slowest (3x fastest) gets 500 pts."""
    # Extract scoring logic from features/poll/router.py
    # Test with known timestamps and verify point distribution

def test_multi_select_scoring_proportional():
    """Multi-select: (R-W)/C formula yields correct partial credit."""
    # R=2 correct, W=1 wrong, C=3 total correct → score = (2-1)/3 = 0.33
```

### P1-007: Concurrent Debate Side Selection

```python
# tests/features/debate/test_debate_concurrent.py
async def test_concurrent_side_picks_balanced_autoassign(server_url):
    """Two participants pick sides simultaneously; auto-assign balances correctly."""
    # 1. Create debate, connect 6 participants
    # 2. Send 3 'debate_pick_side' messages simultaneously (all 'for')
    # 3. Verify auto-assign triggers and assigns remaining 3 to 'against'
    # 4. Assert: no duplicate assignments, sides balanced
```

---

## Appendix C: Knowledge Base References

- **Risk Governance**: `risk-governance.md` — Risk scoring methodology (P x I = Score, >=6 = high)
- **Test Priorities Matrix**: `test-priorities-matrix.md` — P0-P3 criteria
- **Test Levels Framework**: `test-levels-framework.md` — E2E vs API vs Unit selection
- **Test Quality**: `test-quality.md` — No hard waits, <300 lines, <1.5 min, self-cleaning

---

**Generated by:** BMad TEA Agent (Murat)
**Workflow:** `_bmad/tea/testarch/bmad-testarch-test-design`
