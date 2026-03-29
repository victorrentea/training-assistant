# Hermetic E2E Test Cases

## Completed

- [x] **Session start + join**: Host starts session, participant joins, host sees participant
- [x] **Poll lifecycle**: Host creates poll → 2 participants vote → host sees count → close → percentages correct
- [x] **Slide view (cache miss)**: Participant clicks topic → backend fetches from mock Drive → PDF served
- [x] **Slide view (cache hit)**: Second participant views same topic → served from cache, 0 extra Drive calls
- [x] **Follow Me basic**: Stub PPT set to "Clean Code" slide 3 → daemon sends slides_current → participant clicks Follow → correct topic selected

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

## Infrastructure Still Needed

- [ ] Controllable stub IntelliJ adapter (file-based, like PowerPoint stub)
- [ ] Desktop overlay WS mock that records received messages
- [ ] Fixture session folders with pre-populated state for resume test
