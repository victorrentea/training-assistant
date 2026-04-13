# Design: Merge Upload + Paste into Single Menu Entry

**Date:** 2026-04-13  
**Status:** Approved

## Summary

Replace the two separate sidebar nav entries ("Paste" and "Upload") with a single entry "Upload / Paste" that contains both input methods in one view and sends with a single button.

## Sidebar Change

- Remove `data-nav="paste"` and `data-nav="upload"` entries
- Add single entry: icon `upload`, label `Upload / Paste`, `onclick="showView('upload-paste')"`
- Active state highlights this entry when `upload-paste` view is shown
- `VIEWS` array: remove `'paste'` and `'upload'`, add `'upload-paste'`

## New View: `upload-paste-view`

Layout: full-height flex column inside the main content area.

**Upper half — Text field**
- Label: `Text / Code` (small uppercase)
- `<textarea>` fills available space, placeholder: "Paste any text, code snippet, or question here…"
- Max 100 KB (same as current paste)

**Divider**
- Centered `or` with horizontal rules on each side

**Lower half — Drop zone**
- Dashed border drop zone: icon `cloud_upload`, "Drop files to send to host", "or click to browse · max 500 MB"
- Drag-and-drop + click-to-browse (hidden `<input type="file">`)
- Once file selected: show filename + size in the drop zone label
- Max 500 MB (same as current upload)

**Send button**
- Single "Send to Host" button with `send` icon (rotated -45°), bottom-right aligned
- Disabled when both textarea is empty AND no file is selected
- Enabled as soon as text is typed OR a file is chosen (or both)

## Send Logic

On click:
1. If textarea has text → POST `/{sessionId}/api/participant/paste`
2. If file is selected → POST `/{sessionId}/api/upload` (XHR with progress)
3. Both calls fire if both are filled (independent, sequential or parallel)
4. On success: clear textarea, clear file selection, show toast "Sent!"
5. Progress bar appears (below drop zone) only when a file upload is in progress

## Removed

- `paste-view` div and all its contents
- `upload-view` div and all its contents  
- `sendPaste()` function → inlined into new combined `sendUploadPaste()`
- `uploadSend()` / `showUpload()` / `_viewBeforeUpload` → replaced by unified handler
- The two separate nav entries

## Files Affected

- `static/participant.html` only (HTML structure + inline JS)
