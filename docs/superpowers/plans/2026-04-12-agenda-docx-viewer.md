# Agenda .docx Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let participants view a .docx agenda from the session folder, rendered in-browser via mammoth.js.

**Architecture:** Daemon detects `.docx` in session folder, exposes a REST endpoint returning base64-encoded file content (to survive the JSON-over-WS proxy), signals availability via `has_agenda` in the state message. Frontend decodes base64, renders with mammoth.js, displays in a modal.

**Tech Stack:** Python (FastAPI, base64), mammoth.js (CDN), vanilla HTML/JS/CSS.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `daemon/misc/state.py` | Modify | Add `agenda_docx_path: Path \| None` field |
| `daemon/misc/router.py` | Modify | Add `GET /api/participant/agenda` endpoint |
| `daemon/participant/router.py` | Modify | Add `has_agenda: bool` to `ParticipantStateResponse` and state dict |
| `daemon/__main__.py` | Modify | Detect `.docx` at session start, update `misc_state.agenda_docx_path` |
| `static/participant.html` | Modify | Add mammoth.js CDN script, agenda button in status bar, agenda modal markup |
| `static/participant.js` | Modify | Add `toggleAgendaModal()`, handle `has_agenda` in state message |
| `static/participant.css` | Modify | Add `.agenda-content` scoped styles |

---

### Task 1: Daemon State — Add agenda_docx_path to MiscState

**Files:**
- Modify: `daemon/misc/state.py:4-23` (MiscState class)

- [ ] **Step 1: Add `agenda_docx_path` field to MiscState**

In `daemon/misc/state.py`, add after line 23 (`self.gdrive_url`):

```python
self.agenda_docx_path: Path | None = None
```

Also add `from pathlib import Path` at the top of the file (after `import threading`).

- [ ] **Step 2: Commit**

```bash
git add daemon/misc/state.py
git commit -m "feat(agenda): add agenda_docx_path to MiscState"
```

---

### Task 2: Daemon Detection — Scan for .docx in session folder

**Files:**
- Modify: `daemon/__main__.py:874-878` (after gdrive_url resolution block)

- [ ] **Step 1: Add _find_agenda_docx helper function**

Add this function near the other session-folder helpers (around line 510, near `_build_notes_summary_probe`):

```python
def _find_agenda_docx(session_folder: Path | None) -> Path | None:
    """Find a .docx agenda file in the session folder.
    Prefers 'agenda.docx', falls back to first .docx alphabetically."""
    if not session_folder or not session_folder.is_dir():
        return None
    docx_files = sorted(f for f in session_folder.iterdir()
                        if f.suffix.lower() == ".docx" and f.is_file())
    if not docx_files:
        return None
    for f in docx_files:
        if f.name.lower() == "agenda.docx":
            return f
    return docx_files[0]
```

- [ ] **Step 2: Wire detection after gdrive_url resolution**

In the `run()` function, after the gdrive_url block (around line 878, after `log.info("session", f"Google Drive: {_gdrive_url}")`), add:

```python
    # Detect agenda .docx in session folder
    _agenda_path = _find_agenda_docx(config.session_folder)
    if _agenda_path:
        misc_state.agenda_docx_path = _agenda_path
        log.info("session", f"Agenda: {_agenda_path.name}")
```

- [ ] **Step 3: Commit**

```bash
git add daemon/__main__.py
git commit -m "feat(agenda): detect .docx in session folder at startup"
```

---

### Task 3: Daemon REST Endpoint — Serve base64-encoded .docx

**Files:**
- Modify: `daemon/misc/router.py` (add endpoint to participant_router)

- [ ] **Step 1: Add the agenda endpoint**

Read `daemon/misc/router.py` to find the `participant_router` definition and existing endpoints. Add this endpoint:

```python
@participant_router.get("/agenda")
async def get_agenda():
    """Serve the agenda .docx as base64-encoded JSON (survives WS proxy)."""
    import base64
    from daemon.misc.state import misc_state
    path = misc_state.agenda_docx_path
    if not path or not path.exists():
        return JSONResponse({"error": "No agenda available"}, status_code=404)
    try:
        raw = path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return JSONResponse({"data": encoded, "filename": path.name})
    except OSError:
        return JSONResponse({"error": "Failed to read agenda file"}, status_code=500)
```

Note: `JSONResponse` should already be imported in this file. If not, add `from starlette.responses import JSONResponse`.

- [ ] **Step 2: Commit**

```bash
git add daemon/misc/router.py
git commit -m "feat(agenda): add GET /api/participant/agenda endpoint"
```

---

### Task 4: State Message — Add has_agenda field

**Files:**
- Modify: `daemon/participant/router.py:200-237` (ParticipantStateResponse model)
- Modify: `daemon/participant/router.py:559-603` (state_msg dict construction)

- [ ] **Step 1: Add field to Pydantic model**

In `ParticipantStateResponse` (line 237, after `gdrive_url`), add:

```python
    has_agenda: bool = False
```

- [ ] **Step 2: Add field to state_msg dict**

In `get_participant_state()` (around line 602, after the `gdrive_url` entry), add:

```python
        # Agenda .docx availability
        "has_agenda": misc_state.agenda_docx_path is not None and misc_state.agenda_docx_path.exists(),
```

- [ ] **Step 3: Commit**

```bash
git add daemon/participant/router.py
git commit -m "feat(agenda): add has_agenda to participant state message"
```

---

### Task 5: Frontend HTML — Add mammoth.js, button, and modal markup

**Files:**
- Modify: `static/participant.html`

- [ ] **Step 1: Add mammoth.js CDN script**

In the `<head>` section (around line 15, after the existing CDN scripts like marked.min.js), add:

```html
<script src="https://cdn.jsdelivr.net/npm/mammoth@1/mammoth.browser.min.js"></script>
```

- [ ] **Step 2: Add agenda button to status bar**

In the `.status-right` span (line 45, after `session-title` span but before `notes-btn`), add:

```html
        <button id="agenda-btn" class="header-link-btn has-tooltip" data-tooltip="View agenda" onclick="toggleAgendaModal()" style="display:none"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:middle"><path d="M4 1h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm0 1a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H4zm1 2h6v1H5V4zm0 2.5h6v1H5v-1zm0 2.5h4v1H5V9z"/></svg> Agenda</button>
```

- [ ] **Step 3: Add agenda modal overlay**

After the existing modal overlays (after `notes-overlay` block, around line 84), add:

```html
    <div id="agenda-overlay" class="modal-overlay summary-overlay">
      <div class="modal-dialog summary-dialog" onclick="event.stopPropagation()">
        <div class="summary-header">
          <span><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:middle"><path d="M4 1h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm0 1a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H4zm1 2h6v1H5V4zm0 2.5h6v1H5v-1zm0 2.5h4v1H5V9z"/></svg> Agenda</span>
          <button class="summary-close" onclick="closeAgendaModal()">✕</button>
        </div>
        <div id="agenda-content" class="agenda-content" style="padding:1rem; overflow-y:auto; flex:1;"></div>
      </div>
    </div>
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.html
git commit -m "feat(agenda): add mammoth.js CDN, agenda button and modal markup"
```

---

### Task 6: Frontend JS — Toggle logic and mammoth rendering

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Add agenda modal functions**

Near the existing modal functions (after `closeSummaryModal` around line 785), add:

```javascript
// ── Agenda modal ──────────────────────────────────────────────────────────────
let _agendaHtml = null;

function toggleAgendaModal() {
  const overlay = document.getElementById('agenda-overlay');
  if (!overlay) return;
  const opening = !overlay.classList.contains('open');
  overlay.classList.toggle('open');
  _syncSlidesModalBlocking();
  if (opening && !_agendaHtml) {
    const el = document.getElementById('agenda-content');
    el.textContent = 'Loading…';
    fetch(apiBase + '/api/participant/agenda')
      .then(r => r.ok ? r.json() : Promise.reject('not found'))
      .then(data => {
        const binary = atob(data.data);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return mammoth.convertToHtml({ arrayBuffer: bytes.buffer });
      })
      .then(result => {
        _agendaHtml = result.value;
        el.innerHTML = _agendaHtml;
      })
      .catch(() => {
        el.textContent = 'Failed to load agenda.';
      });
  } else if (opening && _agendaHtml) {
    document.getElementById('agenda-content').innerHTML = _agendaHtml;
  }
}

function closeAgendaModal() {
  closeModal('agenda-overlay');
  _syncSlidesModalBlocking();
}
```

- [ ] **Step 2: Add click-outside-to-close listener**

In the `DOMContentLoaded` block where summary/notes overlays get their click-outside listeners (around line 787-799), add a similar block:

```javascript
  const agendaOverlay = document.getElementById('agenda-overlay');
  if (agendaOverlay) {
    let mouseDownOnOverlay = false;
    agendaOverlay.addEventListener('mousedown', e => {
      mouseDownOnOverlay = (e.target === agendaOverlay);
    });
    agendaOverlay.addEventListener('mouseup', e => {
      if (mouseDownOnOverlay && e.target === agendaOverlay) closeAgendaModal();
      mouseDownOnOverlay = false;
    });
  }
```

- [ ] **Step 3: Handle has_agenda in state message**

In the `case 'state':` handler (around line 3251, after the `gdrive_url` block, before `break`), add:

```javascript
        // Agenda .docx availability
        if (msg.has_agenda !== undefined) {
          const agendaBtn = document.getElementById('agenda-btn');
          agendaBtn.style.display = msg.has_agenda ? '' : 'none';
          if (!msg.has_agenda) _agendaHtml = null;
        }
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.js
git commit -m "feat(agenda): add toggleAgendaModal and state handler"
```

---

### Task 7: Frontend CSS — Agenda content styles

**Files:**
- Modify: `static/participant.css`

- [ ] **Step 1: Add scoped styles for rendered .docx content**

At the end of `participant.css`, add:

```css
/* ── Agenda .docx viewer ─────────────────────────────────────────────── */
.agenda-content h1, .agenda-content h2, .agenda-content h3,
.agenda-content h4, .agenda-content h5, .agenda-content h6 {
  margin: .8em 0 .3em;
  color: var(--text);
}
.agenda-content p { margin: .4em 0; line-height: 1.5; }
.agenda-content ul, .agenda-content ol { padding-left: 1.5em; margin: .4em 0; }
.agenda-content table {
  border-collapse: collapse;
  width: 100%;
  margin: .5em 0;
}
.agenda-content th, .agenda-content td {
  border: 1px solid var(--border);
  padding: .3em .5em;
  text-align: left;
}
.agenda-content th { background: var(--surface-alt, var(--surface)); font-weight: 600; }
.agenda-content img { max-width: 100%; height: auto; }
```

- [ ] **Step 2: Commit**

```bash
git add static/participant.css
git commit -m "feat(agenda): add agenda-content CSS styles"
```

---

### Task 8: Integration Test — Verify end-to-end

**Files:**
- No new test files needed (manual verification)

- [ ] **Step 1: Place a test .docx in a session folder**

Create or copy a small `agenda.docx` file into the active session folder. You can create one with:

```bash
# Use python-docx to create a minimal test file
python3 -c "
from docx import Document
doc = Document()
doc.add_heading('Workshop Agenda', level=1)
doc.add_paragraph('9:00 - Welcome and Introductions')
doc.add_paragraph('10:00 - Session 1: Core Concepts')
doc.add_paragraph('12:00 - Lunch Break')
doc.add_paragraph('13:00 - Session 2: Hands-on Lab')
doc.save('/tmp/agenda.docx')
print('Created /tmp/agenda.docx')
"
```

Then copy it to the active session folder.

- [ ] **Step 2: Restart daemon and verify detection**

Restart the daemon and check logs for:
```
HH:MM:SS.f PID [session] Agenda: agenda.docx
```

- [ ] **Step 3: Open participant page and verify button appears**

Open the participant page. The "Agenda" button should be visible in the status bar. Click it to open the modal and verify the document renders correctly.

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(agenda): agenda .docx viewer complete"
```
