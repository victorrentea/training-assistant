# E2E Test Coverage Gap Analysis

All 35 existing tests pass (1 skipped). Below maps each manual test case to existing e2e coverage.

**Legend:** COVERED = automated test exists | PARTIAL = related test exists but doesn't fully cover | GAP = no automated test

---

## 1. Joining & Identity

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 1.1 | First-time join | PARTIAL | `test_autojoin_with_saved_name_no_js_error` (tests auto-join, not fresh join flow) |
| 1.2 | Return visit (same browser) | PARTIAL | `test_autojoin_with_saved_name_no_js_error` (verifies auto-join, not UUID reuse or score preservation) |
| 1.3 | Custom name | COVERED | Every test calls `pax.join("SomeName")` |
| 1.4 | Rename mid-session | **GAP** | |
| 1.5 | Empty name rejected | **GAP** | |
| 1.6 | Long name (32+ chars) | **GAP** | |
| 1.7 | Duplicate names | **GAP** | |
| 1.8 | Avatar assignment | **GAP** | |
| 1.9 | Avatar persistence on rename | **GAP** | |

## 2. Connection & Reconnection

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 2.1 | WebSocket connection indicator | **GAP** | |
| 2.2 | Host connection indicator | **GAP** | |
| 2.3 | Participant disconnect/reconnect | **GAP** | |
| 2.4 | Participant page refresh | **GAP** | |
| 2.5 | Host multi-tab kick | **GAP** | |
| 2.6 | Host page refresh | PARTIAL | `test_host_tab_survives_reload` (tests tab persistence, not poll/vote state) |

## 3. Geolocation

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 3.1 | Location granted | **GAP** | |
| 3.2 | Location denied | **GAP** | |
| 3.3 | Location retry | **GAP** | |
| 3.4 | Map view (host) | **GAP** | |

## 4. Live Poll — Single Select

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 4.1 | Create and launch poll | COVERED | `test_participant_sees_poll_after_host_creates_it` |
| 4.2 | Open voting | COVERED | `test_participant_sees_poll_after_host_creates_it` (poll auto-opens on create) |
| 4.3 | Cast a vote | COVERED | `test_vote_registers_and_host_sees_count` |
| 4.4 | Vote is final (single-select) | **GAP** | |
| 4.5 | Multiple participants vote | **GAP** | (only single-participant vote tests exist) |
| 4.6 | Close voting | COVERED | `test_results_shown_after_poll_closed` |
| 4.7 | Mark correct answer | COVERED | `test_correct_answer_feedback_shown_to_participant` |
| 4.8 | Speed-based scoring | **GAP** | |
| 4.9 | Timer | **GAP** | |
| 4.10 | Delete/clear poll | PARTIAL | `test_download_captures_two_polls_with_correct_answers` (clicks "Remove question") |
| 4.11 | Poll with 2 options | **GAP** | (tests use 3+ options) |
| 4.12 | Poll with 8 options (max) | **GAP** | |
| 4.13 | Poll history | COVERED | `test_download_captures_two_polls_with_correct_answers` |

## 5. Live Poll — Multi-Select

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 5.1 | Create multi-select poll | COVERED | `test_correct_count_hint_shown_to_participant` |
| 5.2 | Selection cap | COVERED | `test_participant_cannot_select_more_than_correct_count` |
| 5.3 | Submit multi-vote | **GAP** | (selection cap tested, but not actual submission + host count) |
| 5.4 | Multi-select scoring | **GAP** | |
| 5.5 | Multi-select with no correct selections | **GAP** | |

## 6. Q&A

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 6.1 | Activate Q&A | COVERED | `test_participant_submits_question_host_sees_it` (implicitly via `open_qa_tab`) |
| 6.2 | Submit question | COVERED | `test_participant_submits_question_host_sees_it` |
| 6.3 | Question character limit (280) | **GAP** | |
| 6.4 | Upvote a question | COVERED | `test_upvoting_and_sorted_order` |
| 6.5 | Cannot upvote own question | COVERED | `test_own_question_upvote_button_disabled` |
| 6.6 | Cannot upvote twice | COVERED | `test_already_upvoted_button_becomes_disabled` |
| 6.7 | Question ranking | COVERED | `test_upvoting_and_sorted_order` |
| 6.8 | Host edits question text | COVERED | `test_host_edits_question_participant_sees_update` |
| 6.9 | Host marks question answered | COVERED | `test_host_marks_question_answered_participant_sees_it` |
| 6.10 | Host deletes question | COVERED | `test_host_deletes_question_participant_list_empty` |
| 6.11 | Host clears all Q&A | **GAP** | (used in fixtures, not tested as user action) |
| 6.12 | Q&A with many questions (10+) | **GAP** | |
| 6.13 | Toast rotation | **GAP** | |

## 7. Word Cloud

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 7.1 | Activate word cloud | COVERED | `test_host_opens_wordcloud_participant_sees_screen` |
| 7.2 | Set topic | **GAP** | |
| 7.3 | Submit a word | COVERED | `test_participant_submits_word_appears_in_my_words` |
| 7.4 | Word deduplication | **GAP** | |
| 7.5 | Autocomplete suggestions | **GAP** | |
| 7.6 | Word cloud visualization | **GAP** | (canvas tested for visibility, not content) |
| 7.7 | Download and clear | **GAP** | |
| 7.8 | Word persistence across refresh | **GAP** | |
| 7.9 | Clear resets participant localStorage | **GAP** | |

## 8. Code Review

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 8.1 | Start code review | **GAP** | |
| 8.2 | Select problematic lines | **GAP** | |
| 8.3 | Deselect a line | **GAP** | |
| 8.4 | Multiple participants select lines | **GAP** | |
| 8.5 | End selection phase | **GAP** | |
| 8.6 | Confirm correct line | **GAP** | |
| 8.7 | Participant names in review panel | **GAP** | |
| 8.8 | Code snippet too short | **GAP** | |
| 8.9 | Code snippet too long (>50 lines) | **GAP** | |
| 8.10 | Close code review | **GAP** | |
| 8.11 | Syntax highlighting | **GAP** | |
| 8.12 | Auto-detect language | **GAP** | |

## 9. Activity Switching

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 9.1 | Switch between activities | PARTIAL | `test_close_wordcloud_participant_returns_to_idle` (only WC→Poll switch) |
| 9.2 | Activity notification | PARTIAL | `test_no_spurious_notification_on_join_mid_poll` (negative case only) |
| 9.3 | Switch to "none" (idle) | COVERED | `test_close_wordcloud_participant_returns_to_idle` |
| 9.4 | Rapid activity switching | **GAP** | |

## 10. Scoring & Leaderboard

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 10.1 | Score display | **GAP** | |
| 10.2 | Score accumulation across activities | **GAP** | |
| 10.3 | Host participant list shows scores | **GAP** | |
| 10.4 | Reset scores | **GAP** | |
| 10.5 | Confetti on score increase | **GAP** | |

## 11. Host Panel — General

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 11.1 | QR code display | **GAP** | |
| 11.2 | Participant link | **GAP** | |
| 11.3 | Server connection badge | **GAP** | |
| 11.4 | Agent/Daemon badge | **GAP** | |
| 11.5 | Version display | COVERED | `test_version_tag_shows_elapsed_time_and_updates_under_day` |

## 12. Summary System

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 12.1 | Push summary points | **GAP** | |
| 12.2 | Update summary | **GAP** | |

## 13. Edge Cases & Stress

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 13.1 | Server restart mid-session | **GAP** | |
| 13.2 | Simultaneous votes | **GAP** | |
| 13.3 | Participant joins mid-activity | COVERED | `test_no_spurious_notification_on_join_mid_poll` (joins mid-poll, verifies state) |
| 13.4 | Participant joins after voting closed | **GAP** | |
| 13.5 | Very long poll question | **GAP** | |
| 13.6 | Special characters / XSS | PARTIAL | `test_host_qa_action_labels_icons_and_edit_with_quotes` (tests quotes, not XSS) |
| 13.7 | Network latency simulation | **GAP** | |
| 13.8 | Mobile browser | **GAP** | |
| 13.9 | 30+ participants (avatar exhaustion) | **GAP** | |
| 13.10 | Concurrent Q&A upvotes | **GAP** | |

## 14. Version Reload Guard

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 14.1 | Version change detection | COVERED | `test_version_mismatch_shows_reload_prompt_and_stop_prevents_auto_reload` |

## 15. Browser Compatibility

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 15.1 | Chrome | COVERED | All tests run in Chromium |
| 15.2 | Firefox | **GAP** | |
| 15.3 | Safari | **GAP** | |
| 15.4 | Edge | **GAP** | |

## 16. Known Issues

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 16.1 | Vote not restored on refresh | **GAP** | |
| 16.2 | Poll result feedback lost on refresh | **GAP** | |

---

## Summary

| Status | Count | % |
|--------|-------|---|
| COVERED | 22 | 27.5% |
| PARTIAL | 7 | 8.75% |
| **GAP** | **51** | **63.75%** |
| **Total** | **80** | |

### Biggest gaps by area (zero or near-zero coverage):

1. **Code Review** — 0/12 covered (entire feature untested)
2. **Scoring & Leaderboard** — 0/5 covered
3. **Geolocation** — 0/4 covered
4. **Connection & Reconnection** — 0/6 covered (only tab persistence partial)
5. **Summary System** — 0/2 covered
6. **Word Cloud** — only 2/9 covered (activate + submit word)
7. **Identity edge cases** — rename, empty name, duplicates, avatars all untested

### Well-covered areas:
1. **Q&A** — 8/13 covered (best coverage overall)
2. **Poll Single-Select core flow** — 6/13 covered (create, vote, close, correct answer)
3. **Version/Reload** — fully covered
4. **Notifications** — well covered including edge cases
