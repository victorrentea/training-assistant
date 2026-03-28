# Participant File Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow participants to upload files (up to 500MB) to the host, with upload button next to the paste button and download icon on host side.

**Architecture:** REST multipart upload (`POST /api/upload`) streams to disk via `shutil.copyfileobj` (never loads full file in memory). Metadata stored in `AppState`. Host downloads via `GET /api/upload/{id}` streaming from disk. WebSocket broadcast notifies host of new files. Temp files stored in `.server-data/uploads/`, cleaned on state reset.

**Tech Stack:** FastAPI (UploadFile streaming), vanilla JS (fetch + FormData, drag-and-drop API), existing WebSocket broadcast system.

---

### Task 1: Backend — State + Upload Feature Router

**Files:**
- Modify: `core/state.py:41-42` (add uploaded_files state next to paste_texts)
- Create: `features/upload/__init__.py`
- Create: `features/upload/router.py`
- Modify: `main.py` (import and mount upload router)

- [ ] **Step 1: Add state fields to AppState**

In `core/state.py`, after `paste_next_id` (line 42), add:

```python
self.uploaded_files: dict[str, list[dict]] = {}  # uuid → [{id, filename, size, disk_path}]
self.upload_next_id: int = 0
```

- [ ] **Step 2: Create the upload feature package**

Create `features/upload/__init__.py` (empty).

Create `features/upload/router.py`:

```python
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.messaging import broadcast_state
from core.state import state

router = APIRouter()

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
UPLOAD_DIR = Path(".server-data") / "uploads"


def _upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    uuid: str = Form(...),
):
    if not uuid or uuid.startswith("__"):
        raise HTTPException(400, "Invalid participant UUID")
    if uuid not in state.participant_names:
        raise HTTPException(400, "Unknown participant")

    filename = (file.filename or "file").strip()
    if not filename:
        filename = "file"
    # Sanitize filename
    filename = Path(filename).name  # strip any directory components
    if not filename:
        filename = "file"

    # Stream to temp file with size check (never load full file in memory)
    state.upload_next_id += 1
    file_id = state.upload_next_id
    dest = _upload_dir() / f"{file_id}_{filename}"

    total = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(64 * 1024)  # 64KB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, "Upload failed")

    if total == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")

    entry = {
        "id": file_id,
        "filename": filename,
        "size": total,
        "disk_path": str(dest),
    }
    state.uploaded_files.setdefault(uuid, []).append(entry)
    await broadcast_state()
    return {"ok": True, "id": file_id, "filename": filename, "size": total}


@router.get("/api/upload/{file_id}")
async def download_file(file_id: int):
    # Find the entry
    for uuid, entries in state.uploaded_files.items():
        for entry in entries:
            if entry["id"] == file_id:
                path = Path(entry["disk_path"])
                if not path.exists():
                    raise HTTPException(404, "File no longer available")
                return FileResponse(
                    path,
                    filename=entry["filename"],
                    media_type="application/octet-stream",
                )
    raise HTTPException(404, "File not found")
```

- [ ] **Step 3: Mount the router in main.py**

In `main.py`, add import and include:

```python
from features.upload import router as upload
```

Mount (no auth — participants need to upload):
```python
app.include_router(upload.router)
```

- [ ] **Step 4: Add uploaded_files to host state broadcast**

In `core/state_builder.py`, inside `_build_host_participants_list()`, after the paste_texts block (line 35), add:

```python
upload_entries = state.uploaded_files.get(pid, [])
if upload_entries:
    participant["uploaded_files"] = [
        {"id": e["id"], "filename": e["filename"], "size": e["size"]}
        for e in upload_entries
    ]
```

- [ ] **Step 5: Add WS dismiss handler for uploaded files**

In `features/ws/router.py`, after the `paste_dismiss` handler block (~line 453), add:

```python
elif msg_type == "upload_dismiss":
    if is_host:
        target_uuid = str(data.get("uuid", ""))
        upload_id = data.get("upload_id")
        if target_uuid in state.uploaded_files and upload_id is not None:
            # Also delete the file from disk
            for entry in state.uploaded_files[target_uuid]:
                if entry["id"] == upload_id:
                    Path(entry["disk_path"]).unlink(missing_ok=True)
                    break
            state.uploaded_files[target_uuid] = [
                e for e in state.uploaded_files[target_uuid] if e["id"] != upload_id
            ]
            if not state.uploaded_files[target_uuid]:
                del state.uploaded_files[target_uuid]
            await broadcast_participant_update()
```

- [ ] **Step 6: Test backend manually**

Run: `python3 -m uvicorn main:app --port 8000`
Test upload: `curl -X POST http://localhost:8000/api/upload -F "file=@some_test_file" -F "uuid=test-uuid"`
Expected: 400 "Unknown participant" (since no WS connection)

- [ ] **Step 7: Commit**

```bash
git add features/upload/ core/state.py core/state_builder.py main.py features/ws/router.py
git commit -m "feat(upload): backend file upload with streaming to disk"
```

---

### Task 2: Participant UI — Upload Button + Modal

**Files:**
- Modify: `static/participant.html:132` (add upload button before paste button)
- Modify: `static/participant.css` (add upload button + modal styles)
- Modify: `static/participant.js` (add upload modal logic)

- [ ] **Step 1: Add upload button HTML**

In `participant.html`, immediately before the paste button (line 132), add:

```html
<button id="upload-btn" class="upload-floating-btn" onclick="openUploadModal()" data-tooltip="Send a file to the host." data-tooltip-emoji="📤"><svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13V4"/><path d="M6 7.5L10 3.5L14 7.5"/><path d="M4.5 13.5v1a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1"/></svg></button>
```

The SVG is an upload icon: arrow going up from a tray/bracket (mirror of the download icon).

- [ ] **Step 2: Add upload modal HTML**

In `participant.html`, after the `paste-overlay` div (line 170), add:

```html
<div id="upload-overlay" class="paste-overlay" onclick="closeUploadModal()">
  <div class="upload-bubble" onclick="event.stopPropagation()">
    <div id="upload-dropzone" class="upload-dropzone" onclick="document.getElementById('upload-file-input').click()">
      <svg width="32" height="32" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:.5;margin-bottom:.4rem"><path d="M10 13V4"/><path d="M6 7.5L10 3.5L14 7.5"/><path d="M4.5 13.5v1a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1"/></svg>
      <div class="upload-dropzone-text">Click to browse or drag &amp; drop</div>
      <div id="upload-file-info" class="upload-file-info"></div>
    </div>
    <input type="file" id="upload-file-input" style="display:none" onchange="onUploadFileSelected(this)">
    <div id="upload-progress-bar" class="upload-progress-bar" style="display:none"><div id="upload-progress-fill" class="upload-progress-fill"></div></div>
    <button id="upload-send-btn" class="paste-send-btn" disabled onclick="sendUploadFile()">Send to host</button>
  </div>
</div>
```

- [ ] **Step 3: Add CSS styles**

In `participant.css`, after the paste button styles (line 2011), add:

```css
/* Upload-to-host floating button */
.upload-floating-btn {
  position: fixed;
  bottom: .75rem;
  right: calc(var(--slides-overlay-width) + .75rem + 52px);
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 1.3rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 3002;
  transition: transform .1s, background .15s, border-color .15s;
  padding: 0;
  line-height: 1;
}
.upload-floating-btn:hover {
  background: rgba(20, 20, 35, 0.97);
  border-color: var(--accent);
}
.upload-floating-btn:active { transform: scale(0.85); }

/* Upload bubble */
.upload-bubble {
  position: fixed;
  bottom: 3.5rem;
  right: calc(var(--slides-overlay-width) + .75rem + 52px);
  width: min(360px, 80vw);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: .75rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  animation: paste-bubble-pop .2s ease-out;
  transform-origin: bottom right;
}
.upload-bubble::after {
  content: '';
  position: absolute;
  bottom: -8px;
  right: 14px;
  width: 16px;
  height: 16px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  transform: rotate(45deg);
}

/* Dropzone */
.upload-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  border: 2px dashed var(--border);
  border-radius: 8px;
  background: var(--bg);
  cursor: pointer;
  padding: 1.5rem 1rem;
  margin-bottom: .5rem;
  transition: border-color .15s, background .15s;
}
.upload-dropzone.drag-over {
  border-color: var(--accent);
  background: rgba(99, 102, 241, 0.08);
}
.upload-dropzone-text {
  color: var(--muted);
  font-size: .85rem;
}
.upload-file-info {
  margin-top: .4rem;
  font-size: .8rem;
  color: var(--accent);
  font-weight: 600;
  word-break: break-all;
  text-align: center;
}

/* Progress bar */
.upload-progress-bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  margin-bottom: .5rem;
  overflow: hidden;
}
.upload-progress-fill {
  height: 100%;
  width: 0%;
  background: var(--accent);
  border-radius: 2px;
  transition: width .2s;
}
```

- [ ] **Step 4: Add JavaScript logic**

In `participant.js`, after `showPasteToast()` function, add:

```javascript
// ── File Upload ──
let _uploadSelectedFile = null;

function openUploadModal() {
  _uploadSelectedFile = null;
  const overlay = document.getElementById('upload-overlay');
  if (overlay) overlay.classList.add('open');
  document.getElementById('upload-file-info').textContent = '';
  document.getElementById('upload-send-btn').disabled = true;
  document.getElementById('upload-progress-bar').style.display = 'none';
  document.getElementById('upload-progress-fill').style.width = '0%';

  // Set up drag-and-drop
  const dz = document.getElementById('upload-dropzone');
  dz.ondragover = e => { e.preventDefault(); dz.classList.add('drag-over'); };
  dz.ondragleave = () => dz.classList.remove('drag-over');
  dz.ondrop = e => {
    e.preventDefault();
    dz.classList.remove('drag-over');
    if (e.dataTransfer.files.length) _setUploadFile(e.dataTransfer.files[0]);
  };
}

function closeUploadModal() {
  const overlay = document.getElementById('upload-overlay');
  if (overlay) overlay.classList.remove('open');
  _uploadSelectedFile = null;
}

function onUploadFileSelected(input) {
  if (input.files.length) _setUploadFile(input.files[0]);
  input.value = ''; // reset so same file can be re-selected
}

function _setUploadFile(file) {
  const maxSize = 500 * 1024 * 1024;
  if (file.size > maxSize) {
    document.getElementById('upload-file-info').textContent = 'File too large (max 500MB)';
    document.getElementById('upload-file-info').style.color = '#ef4444';
    document.getElementById('upload-send-btn').disabled = true;
    _uploadSelectedFile = null;
    return;
  }
  _uploadSelectedFile = file;
  const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
  const sizeStr = file.size < 1024 * 1024 ? `${(file.size / 1024).toFixed(0)} KB` : `${sizeMB} MB`;
  document.getElementById('upload-file-info').textContent = `${file.name} (${sizeStr})`;
  document.getElementById('upload-file-info').style.color = '';
  document.getElementById('upload-send-btn').disabled = false;
}

function sendUploadFile() {
  if (!_uploadSelectedFile) return;
  const file = _uploadSelectedFile;
  const btn = document.getElementById('upload-send-btn');
  btn.disabled = true;
  btn.textContent = 'Uploading...';

  const progressBar = document.getElementById('upload-progress-bar');
  const progressFill = document.getElementById('upload-progress-fill');
  progressBar.style.display = 'block';
  progressFill.style.width = '0%';

  const formData = new FormData();
  formData.append('file', file);
  formData.append('uuid', myUUID);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      progressFill.style.width = Math.round(e.loaded / e.total * 100) + '%';
    }
  };
  xhr.onload = () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      closeUploadModal();
      showUploadToast();
    } else {
      let msg = 'Upload failed';
      try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
      document.getElementById('upload-file-info').textContent = msg;
      document.getElementById('upload-file-info').style.color = '#ef4444';
    }
    btn.textContent = 'Send to host';
    btn.disabled = !_uploadSelectedFile;
  };
  xhr.onerror = () => {
    document.getElementById('upload-file-info').textContent = 'Network error';
    document.getElementById('upload-file-info').style.color = '#ef4444';
    btn.textContent = 'Send to host';
    btn.disabled = !_uploadSelectedFile;
  };
  xhr.send(formData);
}

function showUploadToast() {
  const toast = document.createElement('div');
  toast.textContent = 'File sent!';
  toast.style.cssText = 'position:fixed;bottom:3.5rem;right:calc(var(--slides-overlay-width) + .75rem + 52px);background:var(--accent);color:#fff;padding:.4rem .9rem;border-radius:8px;font-weight:600;font-size:.85rem;z-index:9999;opacity:1;transition:opacity .5s;';
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; }, 1000);
  setTimeout(() => toast.remove(), 1500);
}
```

- [ ] **Step 5: Commit**

```bash
git add static/participant.html static/participant.css static/participant.js
git commit -m "feat(upload): participant upload button, modal with drag-and-drop"
```

---

### Task 3: Host UI — Download Icon per Participant

**Files:**
- Modify: `static/host.js:1241-1246` (add upload icons next to paste icons)
- Modify: `static/host.css` (add upload-icon styles)

- [ ] **Step 1: Add upload file icons in participant list**

In `host.js`, after the `pasteIcons` construction (~line 1245), add:

```javascript
const uploadedFiles = participant.uploaded_files || [];
const uploadIcons = uploadedFiles.map(entry => {
  const sizeMB = (entry.size / (1024 * 1024)).toFixed(1);
  const sizeStr = entry.size < 1024 * 1024 ? `${(entry.size / 1024).toFixed(0)} KB` : `${sizeMB} MB`;
  const title = `${entry.filename} (${sizeStr}) — click to download`;
  return `<span class="upload-icon" title="${escHtml(title)}" data-uuid="${escHtml(pid)}" data-upload-id="${entry.id}" onclick="downloadAndDismissUpload(this)"><svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4v9"/><path d="M6 9.5L10 13.5L14 9.5"/><path d="M4.5 13.5v1a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1"/></svg></span>`;
}).join('');
```

Then update the `<li>` template to include `${uploadIcons}` right after `${pasteIcons}`.

- [ ] **Step 2: Add download + dismiss handler**

In `host.js`, after `copyAndDismissPaste` function, add:

```javascript
function downloadAndDismissUpload(el) {
  const uuid = el.dataset.uuid;
  const uploadId = parseInt(el.dataset.uploadId, 10);
  // Trigger download via hidden link
  const a = document.createElement('a');
  a.href = `/api/upload/${uploadId}`;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Show "Downloaded!" tip
  const tip = document.createElement('span');
  tip.textContent = 'Downloaded!';
  tip.className = 'paste-copied-tip';
  const rect = el.getBoundingClientRect();
  tip.style.left = rect.left + rect.width / 2 + 'px';
  tip.style.top = rect.top - 4 + 'px';
  document.body.appendChild(tip);
  setTimeout(() => tip.remove(), 1200);
  // Send dismiss
  ws.send(JSON.stringify({ type: 'upload_dismiss', uuid: uuid, upload_id: uploadId }));
}
```

- [ ] **Step 3: Add CSS for upload icons**

In `host.css`, after the `.paste-copied-tip` styles, add:

```css
.upload-icon {
  cursor: pointer;
  margin-left: .25rem;
  padding: 2px 4px;
  border-radius: 4px;
  color: #e0e0e0;
  background: rgba(99, 200, 255, 0.25);
  animation: upload-blink 1.2s ease-in-out infinite;
  transition: transform .15s;
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}
@keyframes upload-blink {
  0%, 100% { background: rgba(99, 200, 255, 0.15); }
  50% { background: rgba(99, 200, 255, 0.45); }
}
.upload-icon:hover {
  transform: scale(1.15);
  background: rgba(99, 200, 255, 0.5);
  animation: none;
}
```

- [ ] **Step 4: Commit**

```bash
git add static/host.js static/host.css
git commit -m "feat(upload): host download icons with dismiss"
```

---

### Task 4: Download auth + cleanup on state reset

**Files:**
- Modify: `features/upload/router.py` (add auth to download endpoint)
- Modify: `core/state.py` (cleanup uploaded files on reset)

- [ ] **Step 1: Add host auth to download endpoint**

In `features/upload/router.py`, import `require_host_auth`:

```python
from core.auth import require_host_auth
```

Add `dependencies` to the download route:

```python
from fastapi import Depends

@router.get("/api/upload/{file_id}", dependencies=[Depends(require_host_auth)])
```

- [ ] **Step 2: Cleanup uploaded files on state reset**

In `core/state.py`, at the end of `reset()`, add cleanup for upload directory:

```python
# Clean up uploaded files from disk
import shutil
upload_dir = Path(".server-data") / "uploads"
if upload_dir.exists():
    shutil.rmtree(upload_dir, ignore_errors=True)
```

Add `from pathlib import Path` import at top of `state.py`.

- [ ] **Step 3: Commit**

```bash
git add features/upload/router.py core/state.py
git commit -m "feat(upload): auth on download, cleanup on reset"
```

---

### Task 5: Manual E2E test

- [ ] **Step 1: Start server and test the full flow**

Run: `python3 -m uvicorn main:app --reload --port 8000`

1. Open `http://localhost:8000/` — verify upload button appears to the left of paste button
2. Click upload button — verify modal opens with dropzone
3. Drag a file onto the dropzone — verify filename + size shown
4. Click "Send to host" — verify progress bar fills, "File sent!" toast
5. Open `http://localhost:8000/host` — verify blue download icon appears next to participant
6. Click the download icon — verify file downloads, icon dismissed

- [ ] **Step 2: Test 500MB limit**

Try uploading a file > 500MB — verify client-side rejection with error message.

- [ ] **Step 3: Final commit if any fixes needed**
