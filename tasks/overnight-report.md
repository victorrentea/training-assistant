# Overnight Progress Report — 2026-03-29

## What Was Done

### Hermetic Test Infrastructure (from scratch)
- Built single-container Docker test harness: real FastAPI + real daemon + Playwright
- Stub macOS adapter (`DAEMON_ADAPTER=stub`) for Linux/Docker
- Stub LLM adapter (`LLM_ADAPTER=stub`) for canned Claude responses
- Mock Google Drive HTTP server for slides testing
- Fixture PDF generator for multi-page slide testing
- Controllable stubs via files (`/tmp/stub-powerpoint.json`, `/tmp/stub-intellij.json`)

### Tests Written: 22 passing + 7 skipped (WIP)

| Test | Area | Status |
|------|------|--------|
| Backend healthy | Infra | Pass |
| Daemon connected | Infra | Pass |
| Session start + join | Session | Pass |
| Full poll lifecycle | Poll | Pass |
| Slide view (cache miss) | Slides | Pass |
| Slide view (cache hit) | Slides | Pass |
| Follow Me basic | Slides | Pass |
| Name change visible to host | Participant | Pass |
| Emoji reaction to host | Participant | Pass |
| Q&A submit → host sees | Q&A | Pass |
| Q&A edit → participant sees | Q&A | Pass |
| Q&A delete | Q&A | Pass |
| Q&A mark answered | Q&A | Pass |
| Q&A upvoting + sort order | Q&A | Pass |
| Leaderboard show/hide | Leaderboard | Pass |
| Word cloud submission | Wordcloud | Pass |
| PPTX change detection | Integration | Pass |
| IntelliJ tracking | Integration | Pass |
| Correct answer scoring | Poll | Pass |
| Paste text to host | Participant | Pass |
| Late joiner sees Q&A | Q&A | Pass |
| Self-upvote disabled | Q&A | Pass |
| Quiz generation | Integration | Skip (#98) |
| Conference mode | Mode | Skip (WIP) |
| Zero votes 0% | Poll | Skip (WIP) |
| Code review lines | CodeReview | Skip (WIP) |
| Wordcloud close | Wordcloud | Skip (WIP) |
| Multi-select cap | Poll | Skip (WIP) |
| Participant count | UI | Skip (WIP) |

### Parallelization
- 4 Docker containers run all 29 tests in **~29 seconds** wall time
- Each container is fully isolated (own backend, daemon, session state)

### Configurable Polling Intervals
All daemon and backend polling intervals now env-var-configurable:
- `DAEMON_HEARTBEAT_INTERVAL_SECONDS`, `DAEMON_INTELLIJ_PROBE_INTERVAL_SECONDS`
- `DAEMON_PPT_TRACK_INTERVAL_SECONDS`, `DAEMON_WS_RECONNECT_INTERVAL_SECONDS`
- `BACKEND_SNAPSHOT_INTERVAL_SECONDS`, etc.
- Hermetic tests set all to 0.5s for fast execution

### Bugs Found & Filed
| Issue | Severity | Status |
|-------|----------|--------|
| **#97** Session state leaks between sessions | Critical | **Fixed** |
| **#98** Quiz preview WS import binding | Medium | Filed |
| **#99** PPTX UUID slug mismatch | Medium | Filed |
| **#94** Broadcast dict iteration race | Low | Filed |
| **#93** Materials mirror obsolete | Low | Filed |
| **#95** Overlapping slide requests dedup | Low | Filed |

### Architecture Documentation
- C2 diagram: added Google Drive dependency
- ARCHITECTURE.md: consolidated all C4 diagrams + system interactions inline
- ARCHITECTURE.md: added polling loops & background jobs inventory (30 jobs)
- TESTING.md: created with all test rules and infrastructure docs
- Renamed architecture.md → ARCHITECTURE.md
- Deleted redundant standalone PUML files

## What's Next (Not Yet Done)
1. **Fix 6 WIP tests** — mostly session-scoped API path issues
2. **Gherkin layer** — pytest-bdd with Given/When/Then step definitions
3. **E2E → hermetic migration inventory** — map existing tests/e2e/ to hermetic backlog
4. **Fix #98** (quiz WS import binding) — quick fix
5. **Fix #99** (PPTX slug) — medium fix
6. **Desktop overlay WS mock** — for emoji verification
7. **Transcription fixture files** — for transcript integration point
