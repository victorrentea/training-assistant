# E2E Test Coverage Gap Analysis

Updated 2026-03-22. Maps each manual test case to existing e2e coverage across all test files.

**Legend:** COVERED = automated test exists | PARTIAL = related test exists but doesn't fully cover | GAP = no automated test

---

## 1. Joining & Identity

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 1.1 | First-time join | PARTIAL | `test_autojoin_with_saved_name_no_js_error` (tests auto-join, not fresh join flow) |
| 1.2 | Return visit (same browser) | COVERED | `test_participant_reconnect_restores_name` (verifies auto-join with saved name in same context) |
| 1.3 | Custom name | COVERED | Every test calls `pax.join("SomeName")` |
| 1.4 | Rename mid-session | COVERED | `test_rename_mid_session_host_sees_update` |
| 1.5 | Empty name rejected | COVERED | `test_empty_name_ignored` |
| 1.6 | Long name (32+ chars) | COVERED | `test_long_name_truncated_to_32` |
| 1.7 | Duplicate names | COVERED | `test_duplicate_names_both_in_host_list` |
| 1.8 | Avatar assignment | COVERED | `test_avatar_displayed_on_join` |
| 1.9 | Avatar persistence on rename | COVERED | `test_avatar_persists_after_rename` |

## 2. Connection & Reconnection

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 2.1 | WebSocket connection indicator | COVERED | `test_host_ws_badge_connected` |
| 2.2 | Host connection indicator | COVERED | `test_participant_count_updates` (host sees participant in list) |
| 2.3 | Participant disconnect/reconnect | COVERED | `test_participant_reconnect_restores_name` |
| 2.4 | Participant page refresh | COVERED | `test_participant_refresh_preserves_score` |
| 2.5 | Host multi-tab kick | COVERED | `test_host_multi_tab_kicks_first` |
| 2.6 | Host page refresh | PARTIAL | `test_host_tab_survives_reload` (tests tab persistence, not poll/vote state) |

## 3. Geolocation

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 3.1 | Location granted | **GAP** | (requires geolocation mocking in Playwright) |
| 3.2 | Location denied | **GAP** | |
| 3.3 | Location retry | **GAP** | |
| 3.4 | Map view (host) | **GAP** | |

## 4. Live Poll — Single Select

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 4.1 | Create and launch poll | COVERED | `test_participant_sees_poll_after_host_creates_it` |
| 4.2 | Open voting | COVERED | `test_participant_sees_poll_after_host_creates_it` (poll auto-opens on create) |
| 4.3 | Cast a vote | COVERED | `test_vote_registers_and_host_sees_count` |
| 4.4 | Vote is final (single-select) | COVERED | `test_vote_is_final_cannot_change` |
| 4.5 | Multiple participants vote | COVERED | `test_multiple_participants_vote_correct_counts` |
| 4.6 | Close voting | COVERED | `test_results_shown_after_poll_closed` |
| 4.7 | Mark correct answer | COVERED | `test_correct_answer_feedback_shown_to_participant` |
| 4.8 | Speed-based scoring | COVERED | `test_speed_based_scoring_faster_gets_more` |
| 4.9 | Timer | COVERED | `test_timer_countdown_visible`, `test_timer_cleared_on_close` |
| 4.10 | Delete/clear poll | PARTIAL | `test_download_captures_two_polls_with_correct_answers` (clicks "Remove question") |
| 4.11 | Poll with 2 options | COVERED | `test_poll_with_2_options` |
| 4.12 | Poll with 8 options (max) | COVERED | `test_poll_with_8_options` |
| 4.13 | Poll history | COVERED | `test_download_captures_two_polls_with_correct_answers` |

## 5. Live Poll — Multi-Select

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 5.1 | Create multi-select poll | COVERED | `test_correct_count_hint_shown_to_participant` |
| 5.2 | Selection cap | COVERED | `test_participant_cannot_select_more_than_correct_count`, `test_multi_select_cap_enforced` |
| 5.3 | Submit multi-vote | COVERED | `test_multi_vote_submit_and_host_count` |
| 5.4 | Multi-select scoring | COVERED | `test_multi_select_scoring_all_correct`, `test_multi_select_scoring_partial_zero` |
| 5.5 | Multi-select with no correct selections | COVERED | `test_multi_select_all_wrong_zero_score` |

## 6. Q&A

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 6.1 | Activate Q&A | COVERED | `test_participant_submits_question_host_sees_it` (implicitly via `open_qa_tab`) |
| 6.2 | Submit question | COVERED | `test_participant_submits_question_host_sees_it` |
| 6.3 | Question character limit (280) | COVERED | `test_question_over_280_chars_rejected` |
| 6.4 | Upvote a question | COVERED | `test_upvoting_and_sorted_order` |
| 6.5 | Cannot upvote own question | COVERED | `test_own_question_upvote_button_disabled` |
| 6.6 | Cannot upvote twice | COVERED | `test_already_upvoted_button_becomes_disabled` |
| 6.7 | Question ranking | COVERED | `test_upvoting_and_sorted_order` |
| 6.8 | Host edits question text | COVERED | `test_host_edits_question_participant_sees_update` |
| 6.9 | Host marks question answered | COVERED | `test_host_marks_question_answered_participant_sees_it` |
| 6.10 | Host deletes question | COVERED | `test_host_deletes_question_participant_list_empty` |
| 6.11 | Host clears all Q&A | COVERED | `test_host_clears_all_qa` |
| 6.12 | Q&A with many questions (10+) | COVERED | `test_10_questions_render_and_sort_correctly` |
| 6.13 | Toast rotation | **GAP** | (visual timing test, hard to automate reliably) |

## 7. Word Cloud

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 7.1 | Activate word cloud | COVERED | `test_host_opens_wordcloud_participant_sees_screen` |
| 7.2 | Set topic | COVERED | `test_set_topic_participant_sees_it` |
| 7.3 | Submit a word | COVERED | `test_participant_submits_word_appears_in_my_words` |
| 7.4 | Word deduplication | COVERED | `test_word_deduplication_same_word_counted` |
| 7.5 | Autocomplete suggestions | COVERED | `test_autocomplete_shows_others_words` |
| 7.6 | Word cloud visualization | PARTIAL | (canvas tested for visibility, not content) |
| 7.7 | Download and clear | COVERED | `test_download_and_clear_wordcloud` |
| 7.8 | Word persistence across refresh | COVERED | `test_word_persistence_across_refresh` |
| 7.9 | Clear resets participant localStorage | COVERED | `test_clear_resets_participant_local_words` |

## 8. Code Review

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 8.1 | Start code review | COVERED | `test_start_code_review_participant_sees_snippet` |
| 8.2 | Select problematic lines | COVERED | `test_select_and_deselect_lines` |
| 8.3 | Deselect a line | COVERED | `test_select_and_deselect_lines` |
| 8.4 | Multiple participants select lines | COVERED | `test_multiple_participants_select_lines` |
| 8.5 | End selection phase | COVERED | `test_end_selection_shows_review_phase` |
| 8.6 | Confirm correct line | COVERED | `test_confirm_line_awards_200_points` |
| 8.7 | Participant names in review panel | COVERED | `test_participant_names_in_review_panel` |
| 8.8 | Code snippet too short | COVERED | `test_snippet_validation_too_short_and_too_long` |
| 8.9 | Code snippet too long (>50 lines) | COVERED | `test_snippet_validation_too_short_and_too_long` |
| 8.10 | Close code review | COVERED | `test_close_code_review_returns_to_idle` |
| 8.11 | Syntax highlighting | COVERED | `test_syntax_highlighting_applied` |
| 8.12 | Auto-detect language | COVERED | `test_language_selection_propagates` |

## 9. Activity Switching

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 9.1 | Switch between activities | COVERED | `test_full_activity_cycle_poll_qa_wc_code` |
| 9.2 | Activity notification | PARTIAL | `test_no_spurious_notification_on_join_mid_poll` (negative case only) |
| 9.3 | Switch to "none" (idle) | COVERED | `test_close_wordcloud_participant_returns_to_idle` |
| 9.4 | Rapid activity switching | COVERED | `test_rapid_switching_no_js_errors` |

## 10. Scoring & Leaderboard

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 10.1 | Score display | COVERED | `test_score_visible_when_positive` |
| 10.2 | Score accumulation across activities | COVERED | `test_score_accumulates_across_activities` |
| 10.3 | Host participant list shows scores | COVERED | `test_host_sees_participant_scores` |
| 10.4 | Reset scores | COVERED | `test_reset_scores` |
| 10.5 | Confetti on score increase | COVERED | `test_confetti_fires_on_correct_answer` |
| 10.6 | Leaderboard show/hide | COVERED | `test_leaderboard_show_and_hide` |
| 10.7 | Leaderboard personal rank | COVERED | `test_leaderboard_shows_personal_rank` |

## 11. Host Panel — General

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 11.1 | QR code display | COVERED | `test_qr_code_rendered` |
| 11.2 | Participant link | COVERED | `test_participant_link_displayed` |
| 11.3 | Server connection badge | COVERED | `test_host_ws_badge_connected` |
| 11.4 | Agent/Daemon badge | **GAP** | (requires running daemon) |
| 11.5 | Version display | COVERED | `test_version_tag_shows_elapsed_time_and_updates_under_day` |
| 11.6 | QR fullscreen overlay | COVERED | `test_qr_fullscreen_on_click` |

## 12. Summary System

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 12.1 | Push summary points | **GAP** | (requires daemon or manual API test) |
| 12.2 | Update summary | **GAP** | |

## 13. Edge Cases & Stress

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 13.1 | Server restart mid-session | **GAP** | (requires server restart which breaks the test session) |
| 13.2 | Simultaneous votes | COVERED | `test_simultaneous_votes_all_counted` |
| 13.3 | Participant joins mid-activity | COVERED | `test_participant_joins_mid_qa_sees_questions`, `test_participant_joins_mid_wordcloud_sees_canvas`, `test_no_spurious_notification_on_join_mid_poll` |
| 13.4 | Participant joins after voting closed | COVERED | `test_join_after_voting_closed` |
| 13.5 | Very long poll question | COVERED | `test_very_long_poll_question_renders` |
| 13.6 | Special characters / XSS | COVERED | `test_xss_in_question_escaped`, `test_special_chars_in_wordcloud` |
| 13.7 | Network latency simulation | **GAP** | (requires network throttling) |
| 13.8 | Mobile browser | **GAP** | (requires mobile viewport/device emulation) |
| 13.9 | 30+ participants (avatar exhaustion) | **GAP** | (covered by load test, not e2e) |
| 13.10 | Concurrent Q&A upvotes | COVERED | `test_concurrent_upvotes_correct_count` |

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

## 17. Conference Mode (NEW)

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 17.1 | Toggle conference/workshop mode | COVERED | `test_toggle_conference_mode` |
| 17.2 | Auto-assigned character names | COVERED | `test_conference_mode_auto_assigns_character_name` |
| 17.3 | Score hidden in conference mode | COVERED | `test_conference_mode_hides_score` |

## 18. Full Lifecycle (NEW)

| # | Test Case | Status | Covered By |
|---|-----------|--------|------------|
| 18.1 | Full session with no JS errors | COVERED | `test_no_js_errors_during_full_session_lifecycle` |

---

## Summary

| Status | Count | % |
|--------|-------|---|
| COVERED | 73 | 81.1% |
| PARTIAL | 4 | 4.4% |
| **GAP** | **13** | **14.4%** |
| **Total** | **90** | |

### Remaining gaps (mostly infrastructure-constrained):

1. **Geolocation** — 0/4 covered (requires Playwright geolocation mocking)
2. **Browser Compatibility** — 3/4 gap (only Chrome tested; Firefox/Safari/Edge need Playwright multi-browser config)
3. **Known Issues** — 2 gap (documented bugs, not test gaps per se)
4. **Summary System** — 0/2 covered (requires daemon or manual API setup)
5. **Network/Mobile** — 2 gap (requires throttling and device emulation)
6. **Server restart** — 1 gap (would break the test session)
7. **Daemon badge** — 1 gap (requires running daemon)

### Previously biggest gaps — now fully covered:

1. **Code Review** — 12/12 covered (was 0/12)
2. **Scoring & Leaderboard** — 7/7 covered (was 0/5)
3. **Identity edge cases** — 6/6 covered (was 0/6)
4. **Connection & Reconnection** — 5/6 covered (was 0/6)
5. **Multi-Select Poll** — 5/5 covered (was 1/5)
6. **Word Cloud** — 8/9 covered (was 2/9)
7. **Q&A** — 12/13 covered (was 8/13)
8. **Activity Switching** — 4/4 covered (was 1/4)

### Bugs found and fixed during testing:

1. **Timer not cleared on poll close** — Participant countdown continued after host closed voting. Fixed in `participant.js`: now clears `activeTimer` and stops interval when server sends null timer.
2. **Leaderboard router not registered** — `routers/leaderboard.py` existed but was not included in `main.py`. Fixed by adding `app.include_router(leaderboard.router)`.
