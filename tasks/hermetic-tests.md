# Hermetic E2E Test Cases

## Completed

- [x] **Session start + join**: Host starts session, participant joins, host sees participant
- [x] **Poll lifecycle**: Host creates poll → 2 participants vote → host sees count → close → percentages correct
- [x] **Slide view (cache miss)**: Participant clicks topic → backend fetches from mock Drive → PDF served
- [x] **Slide view (cache hit)**: Second participant views same topic → served from cache, 0 extra Drive calls
- [x] **Follow Me basic**: Stub PPT set to "Clean Code" slide 3 → daemon sends slides_current → participant clicks Follow → correct topic selected
- [x] **Name change**: Participant renames → host sees new name in participant list
- [x] **Emoji reaction to host**: Participant clicks emoji → host page shows floating emoji
- [x] **Q&A submission**: Participant submits question → host sees it in Q&A panel
- [x] **Q&A host edit**: Host edits question → participant sees updated text
- [x] **Word cloud submission**: Host opens wordcloud → participant submits word → appears in "my words"

---

## Slides & PDF Viewing

- [ ] **PDF download**: Participant can download the PDF file to their browser (not just inline view)
- [ ] **Slide scroll persistence**: Participant scrolls topic A to page 3, switches to topic B, comes back to A → auto-scrolled to page 3
- [ ] **Slide cache states (host tooltip)**: Host sees slide cache status in tooltip over folder icon:
  - [ ] Not cached state
  - [ ] Loading/downloading state
  - [ ] Cached state
- [ ] **Live slide update (active viewer)**: PPTX mtime changes → daemon sends `slide_invalidated` → backend re-downloads from mock Drive → participant viewing that topic sees PDF refresh on the same page
- [ ] **Live slide update (not viewing)**: Same trigger, but participant is on a different topic → updated slide shows "new"/"updated" badge in slides list
- [ ] **Overlapping uncached requests (#95)**: Two participants request same uncached slide simultaneously → only 1 Drive call, both get the PDF

## Follow Me (Host Slide Tracking)

- [ ] **Follow across topics**: Host moves to a different topic → participant auto-navigates to new topic + page
- [ ] **Scroll away disables follow**: While following, participant scrolls manually → Follow button blinks then turns off
- [ ] **Re-follow after scroll**: After scrolling away, click Follow again → jumps back to host's current slide
- [ ] **Re-follow after close**: Participant closes overlay (X), clicks Follow → opens on host's current topic + page

## Host UI Status Indicators

- [ ] **Slides collection tooltip**: Host sees list of slides viewed during session in PowerPoint icon tooltip
- [ ] **IntelliJ state**: Host sees current Git project + branch in branch icon tooltip (requires controllable stub)
- [ ] **PowerPoint state**: Host sees current presentation + slide in PowerPoint icon tooltip

## Participant Interactions

- [ ] **Emoji reaction**: Participant clicks emoji → appears on host page AND desktop overlay mock receives it via WS
- [ ] **Name change**: Participant renames themselves → host participant list updates with new name
- [ ] **Paste text**: Participant pastes text → host sees paste icon → host can view/download pasted text
- [ ] **File upload**: Participant uploads file → host sees upload icon → host can download the file

## Session Lifecycle (Multi-Session)

- [ ] **Two sessions in one day**:
  1. Host creates workshop session → daemon creates folder in sessions root
  2. Participant A joins → host sees them
  3. Host clicks stop → session ends
  4. Host creates a new session of type "talk"
  5. Participant B joins the talk
  6. Participant A's WS disconnected, but A still in host list (history)
  7. Participant B in host list with active connection
  8. Daemon disk storage points to talk as active session
  9. Participant B sends emoji → host receives it
  10. Host closes talk → returns to landing page
  11. Host resumes the workshop
  12. Participant A auto-rejoins and appears connected

- [ ] **Materials accessible after session end**: Host creates session → participant joins → host closes → participant's WS closes but slides + notes remain accessible

- [ ] **Resume existing session from disk**: Pre-existing folder in sessions root → host opens landing page → sees it listed → clicks to resume → session initialized in that folder → host closes → daemon global state shows no active session

## From Existing E2E Suite (to migrate)

### Poll (advanced)
- [ ] **Zero votes → 0%**: Close poll with no votes → all options show 0%
- [ ] **Correct answer feedback**: Mark correct → participant sees green/red feedback
- [ ] **Correct count hint**: Multi-select shows "select N" hint
- [ ] **Multi-select cap enforced**: Can't select more than correct_count options
- [ ] **Multi-vote submit + host count**: Multi-select voting and host count update
- [ ] **Multi-select scoring (all correct)**: Full score when all correct
- [ ] **Multi-select scoring (partial wrong)**: Zero score on partial-wrong
- [ ] **Timer countdown visible**: Poll timer appears and counts down
- [ ] **Timer cleared on close**: Timer disappears when poll closes
- [ ] **Poll download text**: Download captures two polls with correct answers

### Q&A
- [ ] **Question submission**: Participant submits question → host sees it
- [ ] **Question editing**: Host edits question → participant sees update
- [ ] **Question deletion**: Host deletes question → participant list empty
- [ ] **Question answered**: Host marks answered → participant sees checkmark
- [ ] **Upvoting + sort order**: Multiple participants upvote → questions sorted by votes
- [ ] **Self-upvote disabled**: Can't upvote own question
- [ ] **Already-upvoted disabled**: Upvote button disabled after voting
- [ ] **Late joiner sees Q&A**: Participant joins mid-Q&A → sees existing questions

### Word Cloud
- [ ] **Word cloud visible**: Host opens wordcloud → participant sees canvas
- [ ] **Word submission**: Participant submits word → appears in "my words"
- [ ] **No JS errors on submit**: Word submission doesn't trigger JS errors
- [ ] **Close wordcloud**: Host closes → participant returns to idle
- [ ] **Late joiner sees canvas**: Participant joins mid-wordcloud → sees it
- [ ] **Special chars in wordcloud**: Unicode characters handled correctly

### Code Review
- [ ] **Create snippet**: Host pastes code → participant sees line selection UI
- [ ] **Line selection + confirm**: Participant flags lines → host confirms → scoring
- [ ] **Status transitions**: idle → selecting → reviewing flow
- [ ] **Create rejects empty**: Empty snippet returns error

### Leaderboard
- [ ] **Show + hide**: Host triggers leaderboard show → participants see top 5 → host hides
- [ ] **Personal rank**: Each participant sees their own rank

### Conference Mode
- [ ] **Toggle mode**: Host switches to conference → participants see character names
- [ ] **Auto character name**: Conference mode auto-assigns character names
- [ ] **Scores hidden**: Conference mode hides participant scores

### UI/UX
- [ ] **Escape closes modals**: Escape key closes all participant modals
- [ ] **Auto-join no JS errors**: Returning participant auto-joins without console errors
- [ ] **Host tab survives reload**: Active tab persists after host page reload
- [ ] **Version tag elapsed time**: Version tag shows deploy age and updates
- [ ] **Notification button states**: Hidden on load, hidden after fresh join, visible for returning participant
- [ ] **No spurious notification on mid-poll join**: Regression test
- [ ] **QR code rendered**: QR code visible on host panel
- [ ] **Participant link displayed**: Session link shown on host panel
- [ ] **Unavailable slide styling**: Unavailable slides crossed out and disabled
- [ ] **Slide NEW badge lifecycle**: No badge before visit → badge after update → clears on click

## Infrastructure Still Needed

- [x] Controllable stub PowerPoint adapter (file-based)
- [ ] Controllable stub IntelliJ adapter (file-based, like PowerPoint stub)
- [ ] Desktop overlay WS mock that records received messages
- [ ] Fixture session folders with pre-populated state for resume test
