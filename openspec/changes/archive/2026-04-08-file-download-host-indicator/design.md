## Context

File upload from participant → Railway already works. The missing piece is the pipeline that moves the file from Railway's temp storage to the daemon's session folder and notifies the host browser with the local disk path. Currently the host has no feedback after a participant uploads: they must check the terminal manually.

The architecture has an important constraint: Railway cannot initiate REST calls to the daemon (Railway → daemon communication is WS-only). The daemon long-polls or maintains a WS connection to Railway.

## Goals / Non-Goals

**Goals:**
- Complete the upload pipeline: Railway notifies daemon via WS → daemon downloads → daemon notifies host browser with disk path
- Show a blinking download icon next to the uploading participant in the host list
- Hover tooltip shows full local disk path
- Click copies path to clipboard and dismisses the icon
- Persist uploaded file indicators in session state so host reconnect/resume restores them
- Icon style matches the upload SVG on the participant screen

**Non-Goals:**
- Hosting a "download via host UI" button (file is already on disk)
- Sending the file to Railway again or any re-upload
- Persistent storage of upload history across server restarts

## Decisions

### D1: Railway → daemon notification via existing daemon WS channel
Railway sends a `file_ready_for_download` WS message to the daemon WebSocket (`/ws/daemon`). The daemon then fetches the file via an authenticated REST call (`GET /api/upload/{file_id}`), saves it, and responds with `file_downloaded` over the same WS channel.

**Alternative considered:** Daemon polls `GET /api/status` for pending uploads. Rejected — adds latency and couples the status endpoint to file state.

### D2: Daemon notifies host browser with `file_uploaded` WS push
After successfully saving the file to `{session_folder}/uploads/{filename}`, the daemon pushes `file_uploaded` to the host browser WS (`/ws/daemon` host channel or via Railway broadcast to host WS). Since Railway proxies host state, the cleanest approach is for the daemon to call `POST /api/upload/{file_id}/ack` with `disk_path`, and Railway broadcasts a `file_uploaded` host WS message containing `uuid`, `filename`, and `disk_path`.

**Alternative considered:** Daemon sends host WS message directly. Rejected — the daemon only speaks to Railway, not directly to host browsers.

### D3: Daemon session-state persistence for indicator lifecycle
Daemon stores each uploaded file indicator in session state with `uuid`, `file_id`, `filename`, `disk_path`, and `dismissed` flag. Host clients render from this persisted state (plus live WS events), and Railway only proxies this state to host browsers, so closing and reopening host UI for the same session keeps indicators visible until dismissed.

**Alternative considered:** Keep indicator state client-only. Rejected — host reconnect/resume loses context and forces terminal checks again.

### D4: Dismissal is persisted for the session
When host clicks the icon, host UI sends a dismiss action through Railway proxy (REST or WS). Daemon marks that file indicator as dismissed in session state and Railway relays the updated host snapshot.

**Alternative considered:** Auto-timeout without explicit dismiss. Rejected — host can miss uploads during active facilitation.

### D5: Icon style
Reuse the same SVG stroke style as the participant upload button (viewBox 0 0 20 20, stroke-width 1.5, round caps) but with a downward arrow (same as existing download arrow icon already in host.js). Blink via a CSS `@keyframes` opacity animation.

## Risks / Trade-offs

- **Large files block daemon download** → Mitigated: file size is capped at 100 MB on upload. Async download (asyncio) prevents blocking the event loop.
- **Session state growth for long workshops** → Mitigated: keep only minimal metadata per uploaded file and keep dismissed entries scoped to current session lifetime.
