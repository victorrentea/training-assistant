# Repara CI — e2e suite migration to rewritten host/participant pages

## Root cause
CI's `lint` + `checks` pass. The 3 `e2e` shards + `hermetic` job have been red since
2026-04-13 (commit 185f873f: participant page rewritten; host UI also reworked).
The e2e suite targets the OLD DOM. New participant page implements **Quiz + Poll only**;
Wordcloud/Q&A/Debate/CodeReview/Notifications/version-reload participant UIs are
"not wired yet". Decision (user): **fix quiz/poll tests, skip unported-feature tests.**

## Known selector changes
- Participant quiz heading: `#content h2` → `.quiz-card h2`
- Participant app-loaded marker: `#main-screen` → (find new root container)
- Host quiz generate button/topic (`#gen-quiz-btn`, `#quiz-topic`): **feature removed** → skip test
- Host close/open voting (`text=Close voting`/`Open voting`, `setQuizStatus`): changed → use API
- Still-valid (rendered by host.js): `.result-row`, `#quiz-display.voting-active`, `N total votes`, `#timer-slider`, `.qa-card`

## Big discovery
The dominant failure across ALL shards was NOT selectors but a session-id resolution bug:
tests/__init__.py makes pytest load conftest twice; the server_url fixture warms the cache
in one copy, but `sapi`/`pax_url` imported via `from conftest import` read the other (cold)
copy, then fall back to daemon `/api/session/active` which is never set on create → None.
Fixed `_get_session_id` to scan sibling conftest copies for the resolved id. This alone
un-broke every API/own-context test. Also found a fire-and-forget vote-vs-close race
(fixed via host.wait_for_votes before close + mark_correct waits for `.markable`).

## Plan
- [x] 1. Fix participant quiz selectors (`#content h2` → `.quiz-card h2`; `#main-screen` → `#display-name`)
- [x] 2. Fix host page-object stale bits (close via API; mark_correct waits `.markable`; wait_for_votes)
- [x] 2b. Fix conftest `_get_session_id` cross-module cache (root cause of most failures)
- [x] 3. Core shard test_main.py green → 14 passed, 22 skipped, 0 failed
- [x] 4. Skip unported classes/tests in test_main.py (WordCloud, QA, Notifications, version, qa-height, generate-btn, zero-votes-pct)
- [x] 5. Shard 3: whole-file skip features/{debate,wordcloud,codereview}/test_e2e.py
- [~] 6. Shard 2: triage test_remaining_gaps.py, features/quiz, features/scoring — IN PROGRESS
- [x] 7. TestProductionSmoke — fixed stale assertion (/api/quiz now 405)
- [ ] 8. hermetic Docker job — 3 slides-follow timing tests (prime cache + downloaded_at broadcast); subagent analysis done
- [ ] 9. Run all 3 e2e shards + hermetic locally green/skipped; commit + push to master
- [ ] 10. Confirm CI green on push

## Skip marker convention
`pytest.mark.skip(reason="Participant <feature> UI not yet ported to new activity-model page (CI repair 2026-06-26)")`

## Review
(to fill in after)
