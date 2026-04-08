## 1. Railway — WS notification to daemon on upload

- [x] 1.1 Add `file_ready_for_download` WS message model in `daemon/ws_messages.py` (fields: `file_id`, `filename`, `size`, `download_url`, `uuid`)
- [x] 1.2 After successful file upload in `railway/features/upload/router.py`, send `file_ready_for_download` to the daemon WS channel
- [x] 1.3 Add `POST /api/upload/{file_id}/ack` endpoint (host-auth, receives `{"disk_path": str}`); store `disk_path` in `uploaded_files` entry and broadcast `file_uploaded` host WS message with `uuid`, `filename`, `size`, `disk_path`
- [x] 1.4 Enforce 100 MB upload limit in `railway/features/upload/router.py` (reject with HTTP 413 if exceeded)
- [x] 1.5 Delete the temp file from Railway storage after ack is received

## 2. Daemon — download file to session folder

- [x] 2.1 Add handler in daemon WS loop for `file_ready_for_download` message type
- [x] 2.2 Download file via authenticated `GET` to `download_url`, save to `{session_folder}/uploads/{filename}` (create `uploads/` dir if needed)
- [x] 2.3 Call `POST /api/upload/{file_id}/ack` with `{"disk_path": "<abs_path>"}` on success

## 3. WS contract update

- [x] 3.1 Update `docs/host-ws.yaml`: add/update `file_uploaded` message with `disk_path` field (alongside existing `uuid`, `filename`, `size`)
- [x] 3.2 Run contract tests to confirm spec is consistent

## 4. Host UI — download icon in participant list

- [x] 4.1 In `static/host.js`, handle incoming `file_uploaded` WS message: store `{uuid, filename, disk_path}` in a client-side map (keyed by `uuid + file_id`)
- [x] 4.2 Re-render participant list (or patch inline) to show download icon when a pending entry exists for a participant
- [x] 4.3 Render the download icon as an SVG (downward arrow, same style as participant upload button), wrapped in a `<span>` with `title="{disk_path}"` and `onclick`
- [x] 4.4 Add CSS `@keyframes` blink/pulse animation for the download icon (opacity 1 → 0.3 → 1)
- [x] 4.5 On icon click: copy `disk_path` to clipboard, remove the entry from the client-side map, re-render to dismiss the icon
- [x] 4.6 Verify icon disappears after click and does not reappear on next state push

## 5. Cleanup

- [x] 5.1 Close GitHub issue #105 (`gh issue close 105`)

## 6. Session-state persistence for host resume

- [ ] 6.1 Persist uploaded file indicators in daemon session state with `uuid`, `file_id`, `filename`, `disk_path`, `dismissed`
- [ ] 6.2 Include non-dismissed daemon-backed uploaded file indicators in host state snapshots (proxied by Railway) so reconnect/resume rehydrates UI
- [ ] 6.3 Add host action (REST or WS via Railway proxy) to mark a file indicator dismissed in daemon session state after copy
- [ ] 6.4 Update `static/host.js` to render from snapshot-backed indicators and keep dismissal behavior consistent after reconnect
- [ ] 6.5 Add/extend tests for reconnect/resume behavior: indicator visible before dismiss, hidden after dismiss, both preserved across host reconnect
