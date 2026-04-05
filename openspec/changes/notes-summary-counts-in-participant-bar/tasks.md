## 1. Daemon — WS messages and broadcast

- [x] 1.1 Add `NotesUpdatedMsg(count: int)` and `SummaryUpdatedMsg(count: int)` to `daemon/ws_messages.py`; register in both `PARTICIPANT_MESSAGES` and `HOST_MESSAGES`
- [x] 1.2 Add `_broadcast_notes_summary_counts(probe)` helper in `daemon/__main__.py` that calls `broadcast()` for both messages
- [x] 1.3 Call `_broadcast_notes_summary_counts` when probe change is detected in the main loop
- [x] 1.4 Call `_broadcast_notes_summary_counts` in `_sync_session_on_reconnect` so counts are re-sent after every daemon WS reconnect

## 2. Daemon — participant /state contract

- [x] 2.1 Replace `notes_content` with `notes_count` (non-empty line count) in participant `/state` response (`daemon/participant/router.py`)
- [x] 2.2 Replace `summary_points` with `summary_count` (len of points list) in participant `/state` response

## 3. Railway — transparent forwarding (no new state)

- [x] 3.1 Confirm `_handle_broadcast` in `railway/features/ws/router.py` forwards `notes_updated` and `summary_updated` to all connected clients without storing anything on Railway state

## 4. Frontend — participant bar

- [x] 4.1 Add `updateNotesCount(count, flash=false)` function: enables/disables `#notes-btn`, updates label to show count, applies yellow flash CSS class when `flash=true`
- [x] 4.2 Add `updateSummaryCount(count, flash=false)` function: same pattern for `#summary-btn`
- [x] 4.3 In `state` case handler, call `updateNotesCount(msg.notes_count)` and `updateSummaryCount(msg.summary_count)` (no flash)
- [x] 4.4 In `notes_updated` WS case, call `updateNotesCount(msg.count, true)` (with flash)
- [x] 4.5 In `summary_updated` WS case, call `updateSummaryCount(msg.count, true)` (with flash)
- [x] 4.6 Add `.count-flash` CSS animation (yellow highlight, ~1s fade) in `participant.css` or inline

## 5. Frontend — host bar

- [x] 5.1 On `notes_updated` WS message, update notes badge to show `📝 (N) Notes.txt` using received count (when full content not yet loaded)
- [x] 5.2 On `summary_updated` WS message, update summary badge to show `🧠 (N) Key Points` using received count (when full points not yet loaded)

## 6. Contracts and docs

- [x] 6.1 Update `docs/participant-ws.yaml` and `docs/host-ws.yaml` with `notes_updated` and `summary_updated` message schemas
- [x] 6.2 Update `apis.md` Notes & Summary section: document new `/state` fields and WS messages precisely; remove mention of Railway caching

## 7. Hermetic test

- [x] 7.1 Write hermetic test in `tests/docker/` that:
  - Loads participant page with mocked `/state` returning `notes_count: 13, summary_count: 17`
  - Asserts Notes button enabled and label contains `13`
  - Asserts Key Points button enabled and label contains `17`
  - Sends `notes_updated {count: 20}` over WS
  - Asserts Notes button label updates to `20` and flash CSS class is present
  - Sends `summary_updated {count: 5}` over WS
  - Asserts Key Points button label updates to `5` and flash CSS class is present
- [x] 7.2 Run contract tests (`tests/daemon/test_ws_contract.py`) to confirm registries and YAML are in sync
