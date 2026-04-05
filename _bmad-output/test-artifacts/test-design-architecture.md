---
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
lastSaved: '2026-03-28'
workflowType: 'testarch-test-design'
inputDocuments:
  - CLAUDE.md (PRD + ADR + tech spec)
  - core/state.py
  - core/messaging.py
  - core/auth.py
  - features/ws/router.py
  - features/poll/router.py
  - features/qa/router.py
  - features/codereview/router.py
  - features/debate/router.py
  - tests/conftest.py
  - tests/ (full suite analysis)
---

# Test Design for Architecture: Training Assistant — Live Workshop Interaction Tool

**Purpose:** Architectural concerns, testability gaps, and NFR requirements for the training-assistant project. This document identifies what must be addressed to strengthen the test suite and reduce production risk.

**Date:** 2026-03-28
**Author:** Murat (TEA Agent)
**Status:** Architecture Review
**Project:** training-assistant
**Reference:** CLAUDE.md (serves as PRD + ADR + tech spec)

---

## Executive Summary

**Scope:** Full system-level test design for a real-time workshop interaction tool (FastAPI + vanilla JS + WebSocket). Covers all features: polls, Q&A, word cloud, code review, debate, leaderboard, quiz generation, session management, and training daemon.

**Business Context:**
- **Impact:** Core product for live workshops/webinars with 30-150 concurrent participants
- **Problem:** Maximize audience engagement during live events — competition, real-time feedback, and interactivity are the product
- **Criticality:** Failure during a live session is a showstopper — no recovery possible once audience is lost

**Architecture:**
- **Key Decision 1:** In-memory state (Python dict), no database — acceptable for short-lived sessions
- **Key Decision 2:** WebSocket-based real-time communication with personalized broadcasts
- **Key Decision 3:** Single-room model, UUID-based participant identity, HTTP Basic Auth for host

**Expected Scale:** 30-150 concurrent WebSocket connections per session

**Risk Summary:**
- **Total risks**: 10
- **High-priority (>=6)**: 1 risk requiring immediate attention (concurrent state mutations)
- **Test effort**: ~13 new tests (~18-29 hours for 1 engineer)

---

## Quick Guide

### BLOCKERS - Must Address (Can't Proceed Without)

**Pre-Implementation Critical Path:**

1. **R-01: asyncio.Lock on state mutations** — Concurrent WebSocket messages can corrupt vote counts, scores, and debate side balance. Add asyncio.Lock guards on hot paths (voting, score updates, debate side selection). (recommended owner: Backend Dev)

**What we need:** Fix R-01 before load testing can validate concurrency safety.

---

### HIGH PRIORITY - Should Validate

1. **R-03: Speed-based scoring accuracy under load** — Vote timestamp precision matters for Kahoot-style scoring. Validate with concurrent voting load test. (implementation phase)
2. **R-04: Debate auto-assign race condition** — Two concurrent side picks can trigger double auto-assign. Add lock or test to confirm idempotency. (implementation phase)
3. **Test data seeding** — Currently tests create state via WS messages + page objects. Consider adding lightweight API seeding for faster test setup. (nice-to-have)

---

### INFO ONLY - No Decisions Needed

1. **Test strategy**: 546 existing tests (54% daemon, 27% feature E2E, 13% workflow E2E, 4% unit, 1% load/contract)
2. **Tooling**: pytest + Playwright (E2E), page object pattern, real server fixture
3. **Execution**: All tests run on every PR (~2-5 min); load tests nightly
4. **Coverage**: ~31 test scenarios (P0-P3), 13 new tests needed
5. **Quality gates**: P0 100% pass, P1 >= 95% pass

---

## For Architects and Devs - Open Topics

### Risk Assessment

**Total risks identified**: 10 (1 high-priority score >=6, 5 medium, 4 low)

#### High-Priority Risks (Score >= 6) - IMMEDIATE ATTENTION

| Risk ID | Category | Description | Probability | Impact | Score | Mitigation | Owner | Timeline |
|---------|----------|-------------|-------------|--------|-------|------------|-------|----------|
| **R-01** | **DATA** | Concurrent vote/debate/score mutations without asyncio.Lock — race conditions can corrupt state under load | 2 | 3 | **6** | Add asyncio.Lock on vote recording, score updates, debate side selection, poll reveal | Backend Dev | Pre-load-test |

#### Medium-Priority Risks (Score 3-5)

| Risk ID | Category | Description | Probability | Impact | Score | Mitigation | Owner |
|---------|----------|-------------|-------------|--------|-------|------------|-------|
| R-02 | TECH | WebSocket reconnect window — participant may miss state update during 3s retry | 2 | 2 | 4 | Full state resync on reconnect (already implemented) | — |
| R-03 | BUS | Speed-based scoring timestamp accuracy under concurrent voting load | 2 | 2 | 4 | Load test with 50+ concurrent voters, validate score distribution | QA |
| R-04 | TECH | Debate auto-assign race — two concurrent side picks trigger double auto-assign | 2 | 2 | 4 | Add asyncio.Lock on debate state OR validate idempotency in tests | Backend Dev |
| R-05 | OPS | Daemon crash loses queued AI requests (quiz/debate cleanup cleared on read) | 2 | 2 | 4 | Acceptable for workshop; test daemon reconnect behavior | — |

#### Low-Priority Risks (Score 1-2)

| Risk ID | Category | Description | Probability | Impact | Score | Action |
|---------|----------|-------------|-------------|--------|-------|--------|
| R-06 | SEC | HTTP Basic Auth on WS via header — no per-message auth | 1 | 2 | 2 | Monitor (HTTPS mitigates) |
| R-07 | PERF | Broadcasting to 150 participants O(N) per mutation | 1 | 2 | 2 | Monitor (load test validates ceiling) |
| R-08 | BUS | Leaderboard score consistency during concurrent updates | 1 | 2 | 2 | Monitor (snapshot at broadcast) |
| R-09 | TECH | Code review smart paste 5s blocking timeout | 1 | 1 | 1 | Monitor (timeout already handled) |
| R-10 | OPS | No automated state backup — server restart loses everything | 2 | 1 | 2 | Monitor (daemon session sync mitigates) |

#### Risk Category Legend

- **TECH**: Technical/Architecture (flaws, integration, scalability)
- **SEC**: Security (access controls, auth, data exposure)
- **PERF**: Performance (SLA violations, degradation, resource limits)
- **DATA**: Data Integrity (loss, corruption, inconsistency)
- **BUS**: Business Impact (UX harm, logic errors, scoring)
- **OPS**: Operations (deployment, config, monitoring)

---

### Testability Concerns and Architectural Gaps

#### 1. Blockers to Fast Feedback

| Concern | Impact | What Architecture Must Provide | Owner | Timeline |
|---------|--------|-------------------------------|-------|----------|
| **No asyncio.Lock on shared state** | Race conditions under concurrent WS load — vote counts, scores, debate sides can corrupt | Add asyncio.Lock guards on `state.votes`, `state.scores`, `state.debate_sides`, `poll_correct` reveal | Backend Dev | Before load test |

#### 2. Architectural Improvements (Should Change)

1. **WebSocket message-level test harness**
   - **Current problem**: All WS interactions tested only via full browser E2E (slow)
   - **Required change**: Add pytest fixture for raw WebSocket client (send JSON, assert response) without browser
   - **Impact if not fixed**: Cannot test WS race conditions at speed; load tests are the only option
   - **Owner**: QA/Backend
   - **Timeline**: P1 improvement

2. **Frontend logic extraction for unit testing**
   - **Current problem**: 4,257 lines in participant.js, 3,253 in host.js — all logic coupled to DOM
   - **Required change**: Extract pure functions (scoring calculation, state diffing, timer math) into testable modules
   - **Impact if not fixed**: Frontend bugs only catchable via slow E2E tests
   - **Owner**: Frontend Dev
   - **Timeline**: P2 improvement (long-term)

---

### Testability Assessment Summary

#### What Works Well

- API-first design with REST + WebSocket — fully testable without browser for most operations
- Page object pattern (`HostPage`, `ParticipantPage`) — clean E2E abstraction
- Opt-in cleanup fixtures (`clean_qa`, `clean_codereview`, etc.) — proper state isolation
- Real server fixture with OS-assigned free port — realistic and parallel-safe
- OpenAPI contract test — catches API drift automatically
- Prometheus metrics instrumented — observability for production monitoring
- Daemon test suite (297 tests) — comprehensive coverage of LLM integration, transcript processing, quiz generation

#### Accepted Trade-offs (No Action Required)

- **In-memory state, no persistence** — acceptable for short-lived workshop sessions (state resets on restart by design)
- **Single-room model** — no multi-room needed; simplifies architecture and testing
- **No frontend build step** — vanilla JS is intentional; trading frontend testability for deployment simplicity
- **Smart paste calls real Claude API** — 5s timeout with graceful fallback; mocking not worth the complexity

---

### Risk Mitigation Plans (High-Priority Risks >= 6)

#### R-01: Concurrent State Mutations Without Locking (Score: 6) - HIGH

**Mitigation Strategy:**

1. Identify all state mutation points in WebSocket message handlers (vote, multi_vote, qa_submit, qa_upvote, debate_pick_side, debate_argument, debate_upvote, codereview_select, wordcloud_word)
2. Add `asyncio.Lock` on critical sections: vote recording + vote_counts(), score updates via `add_score()`, debate side selection + auto_assign_remaining(), poll correct reveal + scoring
3. Load test with 50+ concurrent WebSocket clients sending interleaved messages
4. Validate no score corruption, no duplicate debate assignments, accurate vote counts

**Owner:** Backend Dev
**Timeline:** Before any load testing
**Status:** Planned
**Verification:** Load test P0-006 passes with 50+ concurrent participants and zero data corruption

---

### Assumptions and Dependencies

#### Assumptions

1. Session duration is short (1-8 hours) — state accumulation is bounded
2. Maximum concurrent participants stays under 200
3. Single Railway instance deployment (no horizontal scaling needed)
4. Daemon runs on trainer's Mac with stable network to Railway backend

#### Dependencies

1. asyncio.Lock implementation (R-01) — required before load testing validates concurrency
2. Playwright browser binaries available in CI — required for E2E tests

#### Risks to Plan

- **Risk**: Daemon tests depend on mocked Claude API responses which may drift from real API
  - **Impact**: False confidence in quiz/debate/summary generation
  - **Contingency**: Periodic manual validation against real Claude API; snapshot test fixtures

---

**End of Architecture Document**

**Next Steps:**

1. Review Quick Guide and address R-01 (asyncio.Lock) as top priority
2. Run existing test suite to establish baseline pass rate
3. Add WebSocket-level test fixture for fast concurrency testing (P1)
4. Refer to companion QA doc (test-design-qa.md) for specific test scenarios

**Generated by:** BMad TEA Agent (Murat)
**Workflow:** `_bmad/tea/testarch/bmad-testarch-test-design`
