## 1. Daemon Change Detection

- [ ] 1.1 Add active-session file change tracking for `ai-summary.md` and selected notes `*.txt` (mtime + dedupe snapshot).
- [ ] 1.2 Implement non-empty line counting helper used for both summary and notes documents.
- [ ] 1.3 Trigger change checks in the daemon main loop and reset trackers on session switch/start/resume.

## 2. WS Contract and Publishing

- [ ] 2.1 Add typed WS message model/registry entry for notes-summary freshness notifications.
- [ ] 2.2 Publish the notification to both participant and host channels with fields: `document`, `non_empty_lines`, `updated_at`.
- [ ] 2.3 Ensure payload is notification-only (no full content body) and remains compatible with existing REST fetch flow.

## 3. Client Handling and Validation

- [ ] 3.1 Update participant and host WS handlers to react to notification by refreshing notes/summary data from existing endpoints.
- [ ] 3.2 Update AsyncAPI/API docs (`docs/participant-ws.yaml`, `docs/host-ws.yaml`, `apis.md`) with the new event.
- [ ] 3.3 Add/adjust automated tests for WS contract and runtime behavior (both host and participant receive notifications with correct counts).
