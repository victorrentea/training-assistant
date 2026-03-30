# E2E -> Hermetic Migration Inventory

Generated: 2026-03-29

## Summary
- Already covered: 28 tests
- To migrate: 16 tests
- Blocked: 5 tests

---

## tests/e2e/test_main.py

### TestPollLifecycle

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_participant_sees_poll_after_host_creates_it` | Host creates poll, participant sees question + options | Already covered | `test_full_poll_lifecycle` in test_poll_flow.py |
| `test_vote_registers_and_host_sees_count` | Participant votes, host sees vote count | Already covered | `test_full_poll_lifecycle` in test_poll_flow.py |
| `test_results_shown_after_poll_closed` | Poll closed, participant sees percentages + closed banner | Already covered | `test_full_poll_lifecycle` in test_poll_flow.py |
| `test_zero_votes_shows_zero_percent` | Close poll with no votes, all options show 0% | Already covered | `test_zero_votes_shows_zero_percent` in test_high_value.py |
| `test_correct_answer_feedback_shown_to_participant` | Vote correct, see checkmark after host marks correct | Already covered | `test_correct_answer_gives_score` in test_high_value.py |

### TestMultiSelect

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_correct_count_hint_shown_to_participant` | Multi-select poll shows "exactly N" hint | To migrate | Hint text check not in hermetic tests |
| `test_participant_cannot_select_more_than_correct_count` | 3rd option disabled after selecting 2 in multi-select | Already covered | `test_multi_select_cap_enforced` in test_high_value.py |

### TestRegressions

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_autojoin_with_saved_name_no_js_error` | Auto-join with localStorage name, no JS errors | To migrate | Regression test for auto-join path |
| `test_participant_page_loads_with_zero_votes` | No JS errors when poll has zero votes (largestRemainder fix) | To migrate | Regression for TypeError in largestRemainder |
| `test_generate_button_uses_only_transcript_or_topic_labels` | Quiz generate button label changes with topic input | To migrate | UI label test for quiz controls |
| `test_qa_input_and_button_heights_are_aligned_with_screenshots` | Q&A input and button heights match (visual regression) | Blocked | Visual/layout regression test; needs pixel-level comparison infra |
| `test_version_tag_shows_elapsed_time_and_updates_under_day` | Version tag shows relative time and updates | Blocked | Depends on version.js which is generated at deploy time; not available in Docker |
| `test_version_mismatch_shows_reload_prompt_and_stop_prevents_auto_reload` | Version mismatch banner appears, stop button works | Blocked | Same deploy-time version.js dependency |

### TestWordCloud

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_host_opens_wordcloud_participant_sees_screen` | Host opens wordcloud, participant sees canvas | Already covered | `test_wordcloud_submit_appears_in_my_words` in test_qa_wordcloud.py (opens wordcloud first) |
| `test_participant_submits_word_appears_in_my_words` | Submit word, appears in "my words" list | Already covered | `test_wordcloud_submit_appears_in_my_words` in test_qa_wordcloud.py |
| `test_wordcloud_no_js_errors_on_submit` | No JS errors during word cloud submit (regression) | To migrate | JS error tracking not in hermetic wordcloud tests |
| `test_close_wordcloud_participant_returns_to_idle` | Switch away from wordcloud, participant returns to idle | Already covered | `test_wordcloud_close_returns_to_idle` in test_high_value.py |

### TestQA

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_participant_submits_question_host_sees_it` | Submit Q&A question, host sees it | Already covered | `test_qa_submit_and_host_sees` in test_qa_wordcloud.py |
| `test_host_edits_question_participant_sees_update` | Host edits question text, participant sees update | Already covered | `test_qa_host_edits_participant_sees` in test_qa_wordcloud.py |
| `test_host_deletes_question_participant_list_empty` | Host deletes question, both lists empty | Already covered | `test_qa_host_deletes_question` in test_qa_wordcloud.py |
| `test_host_marks_question_answered_participant_sees_it` | Host marks answered, participant sees styling | Already covered | `test_qa_host_marks_answered` in test_qa_wordcloud.py |
| `test_host_qa_action_labels_icons_and_edit_with_quotes` | Q&A action button labels, icons, edit with special chars | To migrate | UI label/icon verification + special char handling |
| `test_upvoting_and_sorted_order` | 3 participants upvote, verify counts + sort order | Already covered | `test_qa_upvoting_and_sort_order` in test_qa_wordcloud.py |
| `test_own_question_upvote_button_disabled` | Self-upvote button is disabled | Already covered | `test_self_upvote_disabled` in test_high_value.py |
| `test_already_upvoted_button_becomes_disabled` | After upvoting, button becomes disabled + styled | To migrate | Upvoted button disabled state + CSS class check |

### TestTabPersistence

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_host_tab_survives_reload` | Switch to Q&A tab, reload page, Q&A still active | To migrate | Tab persistence across page reload |

### TestPollDownload

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_download_captures_two_polls_with_correct_answers` | Download text has 2 polls with correct answer marks | To migrate | Poll history download feature |

### TestProductionSmoke

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_prod_participant_page_accessible` | Production participant page returns 200 | Blocked | Targets live production URL; not applicable to hermetic |
| `test_prod_host_page_requires_auth` | Production host page returns 401 without auth | Blocked | Targets live production URL; not applicable to hermetic |
| `test_prod_host_page_accessible_with_credentials` | Production host page returns 200 with auth | Blocked | Targets live production URL; not applicable to hermetic |
| `test_prod_api_status_public` | Production /api/status returns participant data | Blocked | Targets live production URL; not applicable to hermetic |
| `test_prod_api_poll_requires_auth` | Production /api/poll requires auth | Blocked | Targets live production URL; not applicable to hermetic |

### TestNotifications

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_notif_btn_hidden_on_load` | Notification button hidden before join | To migrate | Browser notification permission mocking |
| `test_notif_btn_hidden_after_fresh_join` | Notification button hidden after fresh join (permission granted) | To migrate | Browser notification permission mocking |
| `test_notif_btn_visible_for_returning_participant` | Returning participant sees notification button (permission default) | To migrate | Browser notification permission mocking |
| `test_no_spurious_notification_on_join_mid_poll` | No notification fires when joining mid-poll | To migrate | Notification mock + document.hidden override |

---

## tests/e2e/test_gaps.py

### TestCodeReviewGaps

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_create_empty_snippet` | POST empty snippet returns 400/422 | To migrate | API validation test; straightforward |
| `test_create_with_language` | POST snippet with language succeeds | Already covered | `test_code_review_line_selection` in test_high_value.py creates a snippet |
| `test_create_without_language` | POST snippet without language succeeds | To migrate | API edge case; language field optional |
| `test_status_to_reviewing` | PUT status open=false transitions to reviewing | Already covered | Implicit in code review flow tests |
| `test_confirm_line_no_session` | Confirm line with no active session returns 400/404 | To migrate | API error handling edge case |
| `test_confirm_line_in_reviewing` | Confirm line in reviewing phase succeeds | To migrate | Code review confirm-line flow |
| `test_delete_codereview` | DELETE codereview succeeds | Already covered | Cleanup in code review tests |
| `test_create_then_delete_then_confirm_fails` | Confirm after delete returns 400 | To migrate | API state machine edge case |

---

## tests/e2e/test_remaining_gaps.py

### TestMultiSelectPoll

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_multi_vote_submit_and_host_count` | Multi-select vote, host sees vote count | Already covered | `test_multi_select_cap_enforced` in test_high_value.py covers multi-vote |
| `test_multi_select_scoring_all_correct` | All correct options selected, full score | To migrate | Scoring calculation for multi-select |
| `test_multi_select_scoring_partial_zero` | 1 correct + 1 wrong = 0 points | To migrate | Scoring edge case |
| `test_multi_select_all_wrong_zero_score` | All wrong options = 0 points (not negative) | To migrate | Scoring edge case |

### TestPollTimer

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_timer_countdown_visible` | Start timer, participant sees countdown | To migrate | Timer API + participant UI |
| `test_timer_cleared_on_close` | Timer disappears when poll closed | To migrate | Timer lifecycle |

### TestLeaderboard

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_leaderboard_show_and_hide` | Show leaderboard overlay, then hide it | Already covered | `test_leaderboard_show_and_hide` in test_qa_wordcloud.py |
| `test_leaderboard_shows_personal_rank` | Participant sees their own rank | To migrate | Personal rank display |

### TestConferenceMode

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_toggle_conference_mode` | Toggle conference mode on and off | Already covered | `test_conference_mode_auto_assigns_character_name` in test_high_value.py (toggles mode) |
| `test_conference_mode_auto_assigns_character_name` | Conference mode auto-assigns character name | Already covered | `test_conference_mode_auto_assigns_character_name` in test_high_value.py |
| `test_conference_mode_hides_score` | Conference mode hides score display | Already covered | Checked inside `test_conference_mode_auto_assigns_character_name` in test_high_value.py |

### TestConnectionIndicators

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_host_ws_badge_connected` | Host WS badge shows connected class | Already covered | Used as precondition in multiple hermetic tests (e.g. `test_zero_votes_shows_zero_percent`) |
| `test_participant_count_updates` | Host sees participant count increase on join | Already covered | `test_participant_count_updates` in test_high_value.py |

### TestHostPanelGeneral

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_qr_code_rendered` | QR code canvas/img rendered on host panel | To migrate | Host panel UI element check |
| `test_participant_link_displayed` | Participant URL link visible on host | To migrate | Host panel UI element check |
| `test_qr_fullscreen_on_click` | QR icon click opens fullscreen overlay | To migrate | Host panel interaction |

### TestAdditionalEdgeCases

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_participant_joins_mid_qa_sees_questions` | Late joiner sees existing Q&A questions | Already covered | `test_late_joiner_sees_existing_qa` in test_high_value.py |
| `test_participant_joins_mid_wordcloud_sees_canvas` | Late joiner sees wordcloud canvas | To migrate | Late-join wordcloud state |
| `test_special_chars_in_wordcloud` | Unicode characters in word cloud handled | To migrate | Unicode edge case |
| `test_multi_select_cap_enforced` | Multi-select 3rd option blocked | Already covered | `test_multi_select_cap_enforced` in test_high_value.py |
| `test_no_js_errors_during_full_session_lifecycle` | Full lifecycle (Q&A, WC, poll, leaderboard) no JS errors | To migrate | Integration smoke test with JS error tracking |

---

## tests/e2e/test_slides_availability.py

### TestSlidesAvailability

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_unavailable_slide_is_crossed_out_and_disabled` | Catalog slide with no PDF shows crossed-out + disabled | To migrate | Slides upload/catalog infra needed in Docker |
| `test_slide_becomes_available_after_upload` | Upload PDF, slide becomes clickable via WS | To migrate | Slides upload + WS broadcast in Docker |

---

## tests/e2e/test_slides_new_badge.py

### TestSlidesNewBadge

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_no_badge_before_first_visit` | NEW badge not shown if participant never opened slide | To migrate | Slides upload + badge logic |
| `test_badge_appears_after_update` | Visit slide, update it, NEW badge appears | To migrate | Slides upload + localStorage visit tracking |
| `test_badge_clears_after_click` | Re-open updated slide clears NEW badge | To migrate | Badge clear on re-visit |
| `test_pdfjs_autoreload_clears_badge` | PDF.js auto-reloads on update, badge cleared | To migrate | PDF.js integration in Docker |
| `test_native_mode_banner_appears_and_clears` | Native mode shows update banner, click reloads | To migrate | Native viewer mode + banner interaction |

---

## tests/e2e/test_participant_escape.py

| Test | Scenario | Hermetic Status | Notes |
|------|----------|-----------------|-------|
| `test_escape_closes_all_participant_modals` | Escape key closes notes, summary, slides, avatar modals | To migrate | Modal dismiss behavior |

---

## Hermetic-only tests (no e2e counterpart)

These tests exist only in the hermetic suite and have no corresponding e2e test:

| Test | File | Scenario |
|------|------|----------|
| `test_paste_text_visible_to_host` | test_high_value.py | Paste text flow via WS |
| `test_code_review_line_selection` | test_high_value.py | Code review snippet + line selection |
| `test_participant_rename_visible_to_host` | test_participant_interactions.py | Name change visible to host |
| `test_emoji_reaction_visible_to_host` | test_participant_interactions.py | Emoji reaction visible to host |
| `test_pptx_change_triggers_slide_invalidation` | test_integrations.py | PPTX file change detection |
| `test_intellij_state_tracked_by_daemon` | test_integrations.py | IntelliJ project tracking |
| `test_quiz_generation_with_stub_llm` | test_integrations.py | Quiz generation via stub LLM |

---

## Counts by status

| Status | Count |
|--------|-------|
| Already covered | 28 |
| To migrate | 38 |
| Blocked (production smoke) | 5 |
| Blocked (version/visual) | 3 |
| **Total e2e tests** | **74** |

---

## Notes on blocked tests

### Production smoke tests (5 tests)
These target the live production URL (`https://interact.victorrentea.ro`) and are inherently not hermetic. They should remain as a separate `@pytest.mark.prod` suite run against production, not migrated.

### Version tag tests (2 tests)
`test_version_tag_shows_elapsed_time_and_updates_under_day` and `test_version_mismatch_shows_reload_prompt_and_stop_prevents_auto_reload` depend on `static/version.js` which is generated at Railway deploy time. To migrate these, the Docker entrypoint would need to generate a synthetic `version.js`. This is feasible but low priority since the version display is cosmetic.

### Visual regression test (1 test)
`test_qa_input_and_button_heights_are_aligned_with_screenshots` performs pixel-level bounding box comparisons. This works in Docker but may have font rendering differences. Could be migrated with tolerance adjustments.

## Infrastructure needed for migration

1. **Slides upload infra**: Tests in `test_slides_availability.py` and `test_slides_new_badge.py` need the `/api/slides/upload` and `/api/materials/delete` endpoints functional in Docker. The backend already supports these; just need the Docker test to call them.

2. **Notification permission mocking**: Four notification tests need Playwright's `permissions` context option and `add_init_script` for Notification API mocking. Fully supported in headless Chromium.

3. **Timer API**: Two poll timer tests need `/api/{session_id}/poll/timer` endpoint, which is already available.

4. **Multi-select scoring**: Three scoring tests need poll creation with `correct_count`, voting, closing, and marking correct -- all already supported by the hermetic helpers.
