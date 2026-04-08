## Why

When a participant uploads a file to Railway, the daemon downloads it to the session folder on the host's disk — but the host has no way to know where to find it without checking the terminal. This change closes that gap by surfacing the local disk path directly in the host UI next to the participant who sent the file.

## What Changes

- Railway → daemon upload flow: after the daemon downloads the file, it sends a `file_uploaded` WS event back to the host browser so the host panel knows the local path
- Host participant list: a blinking download icon appears next to the uploading participant's name, showing the full local disk path on hover; clicking the icon copies the path to clipboard and the icon disappears
- Daemon session state persists each uploaded file `disk_path` and dismissal status for the active session, so host reconnect/resume restores the same indicators
- The download icon style matches the upload icon on the participant screen (SVG arrow, same stroke style)
- No "download via host UI" button — the file is already on the host's disk, so the path copy is the only action needed

## Capabilities

### New Capabilities

- `file-download-host-indicator`: Blinking download icon in the host participant list after a file is downloaded to the session folder; hover shows full disk path; click copies path to clipboard and dismisses the icon; state survives host reconnect/resume within the same session

### Modified Capabilities

- `sharing`: The existing file upload protocol changes — Railway notifies the daemon via WS, daemon downloads the file and persists `disk_path` in daemon session state; Railway only relays proxy messages and deletes the temp file after daemon confirmation

## Impact

- **Backend (Railway):** `railway/features/upload/router.py` — after storing the file, broadcast a `file_ready_for_download` WS message to the daemon; on daemon ack, delete the temp file
- **Daemon:** add a handler for the `file_ready_for_download` WS message from Railway; download the file to `{session_folder}/uploads/`; persist indicator state; send `file_uploaded` event to host browser WS with `disk_path` via Railway proxy
- **Daemon session state:** persist per-file `disk_path` and dismissal status in active daemon session state, keyed by participant/file
- **Host WS state:** `host-ws.yaml` — include daemon-backed pending file indicators in host state snapshots (proxied by Railway) and add/update `file_uploaded` message schema with `disk_path` field
- **Host UI:** `static/host.js` — handle `file_uploaded` WS message; render blinking download icon per participant; copy-to-clipboard + dismiss on click
