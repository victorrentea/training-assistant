# Manual Test Plan — Workshop Live Interaction Tool

**Scope:** End-to-end manual testing of all activities and interactions.
**Setup:** One host browser at `/host` (HTTP Basic Auth), 1-3 participant browsers at `/`.
**Notation:** [H] = host action, [P] = participant action, [V] = verification step.

---

## 1. Joining & Identity

### 1.1 First-time join
- [P] Open `/` in a fresh browser (cleared localStorage).
- [V] A LOTR name is pre-filled in the name field (fetched from `/api/suggest-name`).
- [P] Click "Join session".
- [V] Participant sees welcome screen with their name, avatar, participant count = 1.
- [V] Name is persisted in `localStorage` (`workshop_participant_name`).
- [V] UUID is persisted in `localStorage` (`workshop_participant_uuid`).

### 1.2 Return visit (same browser)
- [P] Refresh the page after joining.
- [V] Name field is pre-filled with previously entered name.
- [P] Click "Join session".
- [V] Same UUID is reused (check localStorage). Score and identity preserved.

### 1.3 Custom name
- [P] Clear the suggested name, type a custom name (e.g. "Alice").
- [P] Click "Join session".
- [V] Participant sees "Alice" in the header bar.
- [V] Host participant list shows "Alice".

### 1.4 Rename mid-session
- [P] Click the pencil/edit icon next to the name in the header.
- [P] Change name to "Bob" and confirm.
- [V] Header updates to "Bob".
- [V] Host participant list updates to "Bob" in real time.
- [V] UUID remains unchanged. Score is preserved.

### 1.5 Empty name rejected
- [P] Clear the name field entirely, click "Join session".
- [V] Join is blocked or a validation message appears.

### 1.6 Long name (32+ characters)
- [P] Enter a name longer than 32 characters.
- [V] Name is truncated or rejected gracefully.

### 1.7 Duplicate names
- [P1] Join as "Frodo". [P2] Join as "Frodo" in a different browser.
- [V] Both participants appear in host list with the same name but different UUIDs.
- [V] Both can interact independently (vote separately, submit separate questions).

### 1.8 Avatar assignment
- [P] Join as "Gandalf" (a LOTR name).
- [V] Avatar shown is the Gandalf image (not a fallback circle).
- [P2] Join as "CustomName123".
- [V] Avatar is either a LOTR image (deterministic from UUID) or a colored circle with initial.

### 1.9 Avatar persistence on rename
- [P] Join as "Gandalf" (gets gandalf avatar). Rename to "Alice".
- [V] Avatar remains gandalf (assign-once semantics — avatar tied to UUID, not name).

---

## 2. Connection & Reconnection

### 2.1 WebSocket connection indicator
- [P] Join session.
- [V] Green dot appears next to name (connected indicator).

### 2.2 Host connection indicator
- [H] Open host panel.
- [V] Participant header shows "Host" indicator (green dot).
- [H] Close host panel tab.
- [V] Participant's "Host" indicator disappears.

### 2.3 Participant disconnect/reconnect
- [P] Join session, then disable network briefly (or close/reopen laptop lid).
- [V] After reconnection (~3s retry), participant state is restored (name, score).
- [V] Host participant count drops on disconnect, recovers on reconnect.

### 2.4 Participant page refresh
- [P] Join, accumulate some score, then hard-refresh (Cmd+R).
- [P] Re-enter name and join again.
- [V] Score is preserved (server kept it by UUID).
- [V] Current activity state is shown (poll, Q&A, etc.) — not the idle welcome screen (if an activity is active).

### 2.5 Host multi-tab kick
- [H] Open `/host` in tab A. Verify connected.
- [H] Open `/host` in tab B.
- [V] Tab A shows "This session is being taken over" overlay with 5-second countdown.
- [V] After 5 seconds, tab A closes or shows "You may close this tab".
- [V] Tab B is the active host, fully functional.

### 2.6 Host page refresh
- [H] Launch a poll, open voting. Refresh host page.
- [V] Host panel reloads with current state: poll is visible, voting status is preserved.
- [V] Participant list is accurate. Vote counts are correct.

---

## 3. Geolocation

### 3.1 Location granted
- [P] Join session and allow geolocation when prompted.
- [V] "Where are you?" prompt disappears.
- [V] Host sees a city/country string next to the participant.

### 3.2 Location denied
- [P] Join session and deny geolocation.
- [V] Host sees a timezone string (e.g., "Europe/Bucharest") instead of city.

### 3.3 Location retry
- [P] Deny geolocation initially. Click "Where are you?" prompt.
- [V] Browser re-requests geolocation permission.

### 3.4 Map view (host)
- [H] With geolocated participants, click a location string in the participant list.
- [V] Map modal opens showing a marker for the participant.
- [H] Click the map icon in the bottom-right toolbar.
- [V] All geolocated participants shown on map. Timezone-only participants excluded.

---

## 4. Live Poll — Single Select

### 4.1 Create and launch poll
- [H] On Poll tab, type a question + 4 options in the contenteditable area.
- [H] Click "Launch".
- [V] Host center panel shows a bar chart with 0 votes per option.
- [V] Participant still sees idle/welcome (voting not yet open).

### 4.2 Open voting
- [H] Click the open/start voting button.
- [V] Participant sees poll question with clickable option cards.
- [V] "Choose an option to vote." hint is visible.

### 4.3 Cast a vote
- [P] Click one option.
- [V] Option highlights (selected state).
- [V] Host bar chart updates in real time with 1 vote on that option.
- [V] Participant sees updated vote counts after voting.

### 4.4 Vote is final (single-select)
- [P] After voting, click a different option.
- [V] A toast/message appears indicating vote is already registered.
- [V] Vote does NOT change (or if it does, document the actual behavior).

### 4.5 Multiple participants vote
- [P1] Vote option A. [P2] Vote option B. [P3] Vote option A.
- [V] Host chart shows: A=2, B=1, others=0.
- [V] All participants see the same vote counts.

### 4.6 Close voting
- [H] Click close/stop voting button.
- [V] Participants can no longer click options (buttons disabled or hidden).
- [V] A participant who hasn't voted yet cannot vote after closing.

### 4.7 Mark correct answer
- [H] Click on the correct option bar in the chart.
- [V] Bar highlights as "correct".
- [V] Each participant receives a result message: green highlight if they voted correctly, red if wrong.
- [V] Score increases for correct voters (speed-based: 500-1000 pts).
- [V] Confetti animation plays for participants who scored.

### 4.8 Speed-based scoring
- [P1] Vote immediately after poll opens. [P2] Vote 5 seconds later. Both vote correctly.
- [H] Mark the correct answer.
- [V] P1 gets a higher score than P2 (closer to 1000 vs closer to 500).

### 4.9 Timer
- [H] Start a 10-second timer on the poll.
- [V] Both host and participant see a countdown timer.
- [V] Timer counts down from 10 to 0.
- [V] When timer reaches 0, voting closes automatically (or just the timer disappears — verify actual behavior).

### 4.10 Delete/clear poll
- [H] Click close/delete poll button.
- [V] Host center returns to QR code (idle state).
- [V] Participant returns to welcome/idle screen.

### 4.11 Poll with 2 options (minimum)
- [H] Create poll with only 2 options.
- [V] Poll launches correctly. Both options are votable.

### 4.12 Poll with 8 options (maximum)
- [H] Create poll with 8 options.
- [V] All 8 options render correctly on both host chart and participant cards.

### 4.13 Poll history
- [H] Launch and complete several polls throughout the session.
- [V] Poll history is accessible on the host panel (stored per day in localStorage).
- [V] Previous polls are searchable by question text.
- [V] Can re-launch a previous poll from history.

---

## 5. Live Poll — Multi-Select

### 5.1 Create multi-select poll
- [H] Check the "Multi-select" checkbox before launching.
- [H] Set correct_count (e.g., 2 correct answers out of 4).
- [H] Click "Launch" and open voting.
- [V] Participant can toggle multiple options (checkboxes instead of radio).

### 5.2 Selection cap
- [H] Set correct_count = 2.
- [P] Select 2 options, then try to select a 3rd.
- [V] 3rd selection is blocked (or deselects the oldest — verify actual behavior).

### 5.3 Submit multi-vote
- [P] Select 2 options, confirm submission.
- [V] Host chart shows votes distributed across selected options.

### 5.4 Multi-select scoring
- [H] Mark 2 options as correct.
- [P1] Selected both correct options → score = full points.
- [P2] Selected 1 correct + 1 wrong → score = (1-1)/2 = 0 points.
- [P3] Selected 2 correct + 0 wrong → score = (2-0)/2 = full points.
- [V] Verify proportional scoring formula: max(0, (R - W) / C).

### 5.5 Multi-select with no correct selections
- [P] Select only wrong options.
- [V] Score = 0 (not negative).

---

## 6. Q&A

### 6.1 Activate Q&A
- [H] Click the Q&A tab.
- [V] Participant screen switches from idle/poll to Q&A interface.
- [V] Participant sees an input field to submit questions.

### 6.2 Submit question
- [P] Type a question and submit.
- [V] Question appears in the participant's Q&A list (marked as "own").
- [V] Question appears in the host's Q&A panel.
- [V] Participant earns +100 points.

### 6.3 Question character limit
- [P] Try to submit a question longer than 280 characters.
- [V] Submission is blocked or text is truncated. Error message shown.

### 6.4 Upvote a question
- [P2] Click upvote on P1's question.
- [V] Upvote count increases by 1.
- [V] P1 (author) earns +50 points.
- [V] P2 (voter) earns +25 points.

### 6.5 Cannot upvote own question
- [P1] Try to upvote their own question.
- [V] Upvote button is disabled or click has no effect.

### 6.6 Cannot upvote twice
- [P2] Upvote P1's question. Try to upvote it again.
- [V] Second upvote has no effect. Button shows already-upvoted state.

### 6.7 Question ranking
- [P1] Submit question A. [P2] Submit question B. [P3] Upvote question B.
- [V] Question B appears above question A (sorted by upvote count).

### 6.8 Host edits question text
- [H] Click on a question to edit its text.
- [V] Updated text is reflected on all participant screens in real time.

### 6.9 Host marks question as answered
- [H] Toggle the "answered" flag on a question.
- [V] Visual indicator (strikethrough, checkmark, or dimming) appears on all screens.

### 6.10 Host deletes question
- [H] Delete a specific question.
- [V] Question disappears from all participant screens.
- [V] Upvotes/scores already awarded are NOT revoked.

### 6.11 Host clears all Q&A
- [H] Click "Clear all".
- [V] All questions removed from all screens.

### 6.12 Q&A with many questions (10+)
- Submit 10+ questions from multiple participants.
- [V] Scrolling works correctly. Ranking is maintained.
- [V] Performance is acceptable (no lag on updates).

### 6.13 Toast rotation
- [P] Observe the bottom of the Q&A screen.
- [V] Motivational prompts cycle every ~8 seconds (5 different messages).

---

## 7. Word Cloud

### 7.1 Activate word cloud
- [H] Click the Words tab.
- [V] Participant screen switches to word cloud interface.

### 7.2 Set topic
- [H] Type a topic (e.g., "Design Patterns") and click "Push".
- [V] Participant sees the topic displayed above the word input.

### 7.3 Submit a word
- [P] Type a word and submit.
- [V] Word appears in the word cloud visualization (host center panel).
- [V] Participant earns +200 points.

### 7.4 Word deduplication
- [P1] Submit "Java". [P2] Submit "java". [P1] Try to submit "JAVA".
- [V] All treated as "java" (lowercased). Cloud shows "java" with size proportional to count.
- [V] P1 cannot submit the same word twice (deduplicated per participant).

### 7.5 Autocomplete suggestions
- [P] Start typing a word that others have already submitted.
- [V] Autocomplete dropdown shows matching words (excluding words this participant already submitted).

### 7.6 Word cloud visualization
- [V] Host center panel renders a D3-Cloud canvas with words sized by frequency.
- [V] Cloud updates in real time as new words are submitted.

### 7.7 Download and clear
- [H] Click "Download image and close".
- [V] PNG file is downloaded to the host's machine.
- [V] Word cloud is cleared on all screens.
- [V] Participant's local word history is reset.

### 7.8 Word persistence across refresh
- [P] Submit 3 words. Refresh browser.
- [V] After rejoin, participant's submitted words are remembered (localStorage).
- [V] Participant cannot re-submit the same words (dedup still enforced).

### 7.9 Clear resets participant localStorage
- [H] Clear the word cloud.
- [P] Verify localStorage words are reset (can submit the same words again in a new session).

---

## 8. Code Review

### 8.1 Start code review
- [H] On Code tab, paste a code snippet (10-50 lines). Select language (or auto-detect).
- [H] Click "Start Code Review".
- [V] Participant screen switches to code review interface showing the snippet.
- [V] Phase = "selecting": participant can click lines.

### 8.2 Select problematic lines (participant)
- [P] Click line 5 to flag it as problematic.
- [V] Line 5 highlights on the participant's screen.
- [V] Host sees line 5 count increment in real time.

### 8.3 Deselect a line
- [P] Click line 5 again to unflag it.
- [V] Line 5 unhighlights. Host count decrements.

### 8.4 Multiple participants select lines
- [P1] Select lines 3, 5. [P2] Select lines 5, 7. [P3] Select line 5.
- [V] Host sees: line 3 (1 selection), line 5 (3 selections), line 7 (1 selection).

### 8.5 End selection phase
- [H] Click "End" to transition to reviewing phase.
- [V] Participants can no longer select/deselect lines.
- [V] Heatmap appears showing percentage of participants who selected each line.
- [V] Host can click lines to see names of who flagged them.

### 8.6 Confirm correct line
- [H] Click a line to confirm it as a correct finding (e.g., line 5).
- [V] Line 5 is marked as "confirmed" visually (green highlight or checkmark).
- [V] All participants who selected line 5 earn +200 points.
- [V] Scores update in real time on participant screens and host sidebar.

### 8.7 Participant names in review panel
- [H] In reviewing phase, click a selected line.
- [V] Side panel shows names of participants who flagged that line.
- [V] Names are sorted by score ascending (lowest score first).

### 8.8 Code snippet too short
- [H] Try to paste fewer than 10 lines.
- [V] Verify behavior (rejected? accepted? — document actual behavior).

### 8.9 Code snippet too long (>50 lines)
- [H] Try to paste more than 50 lines.
- [V] Snippet is truncated or rejected with error message.

### 8.10 Close code review
- [H] Click close/delete button.
- [V] Code review clears. Participants return to idle screen.

### 8.11 Syntax highlighting
- [H] Start code review with Java snippet, language set to "Java".
- [V] Code is syntax-highlighted appropriately on both host and participant screens.

### 8.12 Auto-detect language
- [H] Leave language as "Auto-detect" and paste Python code.
- [V] Language is correctly detected and syntax highlighting applied.

---

## 9. Activity Switching

### 9.1 Switch between activities
- [H] Start a poll. Then switch to Q&A tab. Then to Word Cloud. Then to Code.
- [V] Each switch changes the participant's screen to the corresponding activity.
- [V] Previous activity data is preserved (poll results still exist when switching back).

### 9.2 Activity notification
- [P] Have browser notification permission granted.
- [H] Switch to a new activity.
- [V] Participant receives a browser notification (e.g., "New poll!" or "Q&A is open").

### 9.3 Switch to "none" (idle)
- [H] Ensure no activity is active (close all activities).
- [V] Participant sees the welcome/idle screen.
- [V] Host center panel shows QR code.

### 9.4 Rapid activity switching
- [H] Rapidly switch between Poll → Q&A → Words → Code → Poll.
- [V] Participant UI keeps up without glitches or stale state.
- [V] No JavaScript errors in console.

---

## 10. Scoring & Leaderboard

### 10.1 Score display
- [P] Earn points via any activity.
- [V] Score appears in top-right as "X pts" (only visible when > 0).
- [V] Score flash animation plays on increase.

### 10.2 Score accumulation across activities
- [P] Earn 100 pts from Q&A, then 200 pts from word cloud, then 800 pts from poll.
- [V] Total score = 1100 pts. Score never resets between activities.

### 10.3 Host participant list shows scores
- [H] With multiple scored participants.
- [V] Each participant row shows their current score.
- [V] Scores update live as points are awarded.

### 10.4 Reset scores
- [H] Click "Reset scores".
- [V] All participant scores drop to 0.
- [V] Participants see their score disappear (or show 0).

### 10.5 Confetti on score increase
- [P] Answer a poll correctly.
- [V] Confetti animation plays. Particle count scales logarithmically with points earned.

---

## 11. Host Panel — General

### 11.1 QR code display
- [H] In idle state, verify QR code is visible in center panel.
- [V] QR code encodes the participant URL.
- [H] Click the QR code.
- [V] Fullscreen overlay appears with large QR code on dark background.

### 11.2 Participant link
- [H] Verify participant URL is displayed in bottom-right area.
- [V] URL is clickable and opens participant page.

### 11.3 Server connection badge
- [V] Bottom-left shows green "Server" badge when WebSocket is connected.
- Stop the server.
- [V] Badge turns red/disconnected.

### 11.4 Agent/Daemon badge
- [V] Shows "Agent: never connected" in red when no daemon is running.
- (If daemon is running) [V] Shows green with last-seen timestamp.

### 11.5 Version display
- [V] Both host and participant pages show version string in bottom-right corner.

---

## 12. Summary System

### 12.1 Push summary points
- [H] POST key points via API: `POST /api/summary { points: ["Point 1", "Point 2"] }`.
- [V] Participant sees a clipboard icon (only visible when summary exists).
- [P] Click the clipboard icon.
- [V] Modal opens showing bullet-pointed summary with timestamp.

### 12.2 Update summary
- [H] Push new summary points (replaces previous).
- [V] Participant modal reflects updated content and timestamp.

---

## 13. Edge Cases & Stress Scenarios

### 13.1 Server restart mid-session
- Start a session with active poll and participants.
- Restart the server.
- [V] All in-memory state is lost (votes, scores, poll, names).
- [V] Participants auto-reconnect after ~3s.
- [V] Participants see idle state (no poll, no score).

### 13.2 Simultaneous votes from many participants
- Have 5+ participants vote within 1 second of each other.
- [V] All votes are counted correctly. No race conditions.
- [V] Host chart updates smoothly.

### 13.3 Participant joins mid-activity
- [H] Start a poll and open voting.
- [P] (new participant) Open `/` and join for the first time.
- [V] New participant immediately sees the active poll and can vote.

### 13.4 Participant joins after voting closed
- [H] Create poll, open voting, close voting.
- [P] (new participant) Join.
- [V] Participant sees the poll but cannot vote (voting closed).

### 13.5 Very long poll question
- [H] Create a poll with a very long question (200+ characters).
- [V] Question text wraps correctly on both host and participant screens.

### 13.6 Special characters in inputs
- [P] Submit a Q&A question with HTML tags: `<script>alert('xss')</script>`.
- [V] Tags are escaped/sanitized. No XSS execution.
- [P] Submit a word cloud word with Unicode: "caf\u00e9", "\u{1F680}".
- [V] Handled gracefully.

### 13.7 Network latency simulation
- [P] Throttle network to slow 3G.
- [V] Voting still works (may be delayed). No duplicate votes.
- [V] WebSocket reconnects gracefully on drops.

### 13.8 Mobile browser
- [P] Open `/` on a mobile browser (iPhone Safari, Android Chrome).
- [V] Layout is responsive. All interactions (voting, Q&A, word cloud, code review) work via touch.
- [V] Name input keyboard works. Vote taps register.

### 13.9 30+ participants (avatar exhaustion)
- Simulate 31+ participants joining.
- [V] First 30 get unique LOTR avatars. 31st gets a duplicate avatar (no crash).

### 13.10 Concurrent Q&A upvotes
- [P1]-[P5] all upvote the same question simultaneously.
- [V] Final upvote count = 5. No double-counting. Author score = base + (5 x 50).

---

## 14. Version Reload Guard

### 14.1 Version change detection
- [P] Join session. Redeploy server (or change `version.js`).
- [V] Participant sees a modal prompting to reload with 5-second countdown.
- [V] User can dismiss or reload immediately.

---

## 15. Browser Compatibility

### 15.1 Chrome (latest)
- Run through core flows (join, vote, Q&A, word cloud, code review).
- [V] All features work.

### 15.2 Firefox (latest)
- Same as 15.1.

### 15.3 Safari (latest)
- Same as 15.1. Pay special attention to WebSocket behavior and localStorage.

### 15.4 Edge (latest)
- Same as 15.1.

---

## 16. Known Issues to Verify

### 16.1 Vote not restored on refresh (GitHub #33)
- [P] Vote in a poll. Clear localStorage. Refresh.
- [V] **Expected bug:** Participant appears un-voted (can vote again). Backend has their vote but doesn't send `my_vote` back in state.

### 16.2 Poll result feedback lost on refresh (GitHub #33)
- [H] Mark correct answers (participant sees green/red result).
- [P] Refresh page.
- [V] **Expected bug:** Poll is visible but no green/red result feedback (one-time `result` message was missed).
