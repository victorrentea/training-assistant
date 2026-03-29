# Hermetic E2E Test Cases

## Completed
- [x] **Session start + join**: Host starts session, participant joins, host sees participant
- [x] **Poll lifecycle**: Host creates poll → 2 participants vote → host sees count → close → percentages correct
- [x] **Slide view (cache miss)**: Participant clicks topic → backend fetches from mock Drive → PDF served
- [x] **Slide view (cache hit)**: Second participant views same topic → served from cache, 0 extra Drive calls

## Slides & PDF Viewing

- [ ] **PDF download**: Participant can download the PDF file to their browser (not just inline view)
- [ ] **Slide scroll persistence**: Participant scrolls topic A to page 3, switches to topic B, comes back to A → auto-scrolled to page 3
- [ ] **Slide cache states (host UI)**: Host sees slide cache status in tooltip over folder icon:
  - [ ] Not cached state (before any participant requests it)
  - [ ] Loading/downloading state (while backend fetches from Drive)
  - [ ] Cached state (after download completes)
- [ ] **Live slide update (active viewer)**: PPTX mtime changes → daemon sends `slide_invalidated` → backend re-downloads from mock Drive → participant viewing that topic sees PDF refresh on the same page they were on
- [ ] **Live slide update (not viewing)**: Same trigger, but participant is on a different topic → the updated slide shows "new"/"updated" badge in the slides list

## Follow Me (Host Slide Tracking)

- [ ] **Basic follow**: Participant clicks "Follow" → immediately shows the host's current slide + page
- [ ] **Follow across topics**: Host moves to a different topic → participant auto-navigates to new topic + page
- [ ] **Scroll away disables follow**: While following, participant scrolls manually → Follow button blinks and turns off
- [ ] **Re-follow after scroll**: After scrolling away, participant clicks Follow again → jumps back to host's current slide
- [ ] **Re-follow after close**: Participant closes slide overlay (X), then clicks Follow → opens overlay on host's current topic + page

## Host UI Status Indicators

- [ ] **Slides collection tooltip**: Host sees list of slides viewed during session in tooltip over the appropriate icon
- [ ] **IntelliJ state**: Host sees current Git project + branch in tooltip over branch icon (requires controllable stub)
- [ ] **PowerPoint state**: Host sees current presentation name + slide number in tooltip over PowerPoint icon

## Participant Interactions

- [ ] **Emoji reaction**: Participant clicks emoji → appears on host page AND desktop overlay mock receives it via WS
- [ ] **Name change**: Participant renames themselves → host participant list updates with new name
- [ ] **Paste text**: Participant pastes text → host sees paste icon in participant list → host clicks icon → can view/download pasted text
- [ ] **File upload**: Participant uploads file → host sees upload icon → host can download the file

## Infrastructure Needed (not yet built)

- [ ] Controllable stub PowerPoint adapter (HTTP API on :9999 to set current presentation + slide)
- [ ] Controllable stub IntelliJ adapter (HTTP API to set project + branch)
- [ ] Desktop overlay WS mock that records received messages (for emoji assertion)
- [ ] `_await_condition()` helper for non-DOM assertions (already built, reuse)
