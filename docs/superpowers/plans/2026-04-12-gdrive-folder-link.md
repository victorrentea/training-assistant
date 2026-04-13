# Google Drive Folder Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the Google Drive web link for the current session folder and show it as a clickable icon on the participant status bar.

**Architecture:** A standalone Python script queries the local Google Drive for Desktop SQLite databases to map a local folder path → Google Drive cloud ID → web URL. The daemon calls this script on session start and stores the result in `MiscState.gdrive_url`. The participant REST state endpoint includes this URL, and the participant UI renders a Google Drive icon button before the Key Points button (hidden when no URL).

**Tech Stack:** Python, SQLite3, FastAPI, vanilla JS/HTML

---

### Task 1: Create `scripts/resolve_gdrive_link.py`

**Files:**
- Create: `scripts/resolve_gdrive_link.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Resolve a local Google Drive folder path to its Google Drive web URL.

Usage: python3 scripts/resolve_gdrive_link.py <local_folder_path>
Prints the Google Drive URL to stdout, or exits with code 1 on failure.
"""
import sqlite3
import sys
from pathlib import Path


def find_drive_dbs() -> tuple[Path, Path] | None:
    """Find the DriveFS mirror and metadata SQLite databases."""
    base = Path.home() / "Library" / "Application Support" / "Google" / "DriveFS"
    if not base.exists():
        return None
    # Find the first account directory (numeric ID)
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and entry.name.isdigit():
            mirror = entry / "mirror_sqlite.db"
            meta = entry / "mirror_metadata_sqlite.db"
            if mirror.exists() and meta.exists():
                return mirror, meta
    return None


def resolve_gdrive_url(local_path: str) -> str | None:
    """Resolve a local Google Drive path to a Google Drive web URL."""
    dbs = find_drive_dbs()
    if not dbs:
        return None
    mirror_db, meta_db = dbs

    folder_name = Path(local_path).name

    # Step 1: find stable_id by folder name in mirror_item
    conn = sqlite3.connect(f"file:{mirror_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT stable_id, local_filename FROM mirror_item WHERE local_filename = ?",
            (folder_name,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    # If multiple matches, try to disambiguate by checking parent path
    stable_ids = [r[0] for r in rows]

    # Step 2: map stable_id → cloud_id via metadata DB
    conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in stable_ids)
        cloud_rows = conn.execute(
            f"SELECT stable_id, cloud_id FROM stable_ids WHERE stable_id IN ({placeholders})",
            stable_ids,
        ).fetchall()
    finally:
        conn.close()

    if not cloud_rows:
        return None

    # If single match, use it; if multiple, pick the last one (most recent stable_id)
    cloud_id = max(cloud_rows, key=lambda r: r[0])[1]
    return f"https://drive.google.com/drive/folders/{cloud_id}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/resolve_gdrive_link.py <local_folder_path>", file=sys.stderr)
        sys.exit(1)
    url = resolve_gdrive_url(sys.argv[1])
    if url:
        print(url)
    else:
        print(f"Could not resolve Google Drive link for: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Test manually**

Run: `python3 scripts/resolve_gdrive_link.py "/Users/victorrentea/My Drive/Cursuri/###sesiuni/2026-04-07..09 AI@Globex"`
Expected: `https://drive.google.com/drive/folders/1Lx2Fv-rZoIemjfzu_uDEQldzDH3kgIMX`

- [ ] **Step 3: Commit**

```bash
git add scripts/resolve_gdrive_link.py
git commit -m "feat: add script to resolve Google Drive folder link from local path"
```

---

### Task 2: Add `gdrive_url` to daemon state and resolve on session start

**Files:**
- Modify: `daemon/misc/state.py` — add `gdrive_url` field to `MiscState`
- Modify: `daemon/__main__.py` — call resolver on session start
- Modify: `daemon/participant/router.py` — add `gdrive_url` to state response

- [ ] **Step 1: Add `gdrive_url` to `MiscState`**

In `daemon/misc/state.py`, add to `__init__`:
```python
self.gdrive_url: str | None = None
```

Add to `sync_from_restore`:
```python
if "gdrive_url" in data:
    self.gdrive_url = data["gdrive_url"]
```

Add to `reset_for_new_session`:
```python
self.gdrive_url = None
```

- [ ] **Step 2: Call resolver on session start in `daemon/__main__.py`**

Add a helper function near the top-level helpers that calls the script:

```python
def _resolve_gdrive_url(session_folder: Path) -> str | None:
    """Resolve Google Drive web URL for a session folder."""
    try:
        from scripts.resolve_gdrive_link import resolve_gdrive_url
        return resolve_gdrive_url(str(session_folder))
    except Exception as e:
        log.error("session", f"Failed to resolve Google Drive link: {e}")
        return None
```

Call it when a session folder is detected (where `session_stack` is populated from `config.session_folder`), and store result in `misc_state`:

```python
from daemon.misc.state import misc_state
gdrive_url = _resolve_gdrive_url(config.session_folder)
if gdrive_url:
    misc_state.gdrive_url = gdrive_url
    log.info("session", f"📂 Google Drive: {gdrive_url}")
```

- [ ] **Step 3: Add `gdrive_url` to participant state response**

In `daemon/participant/router.py`, add to `ParticipantStateResponse`:
```python
gdrive_url: str | None = None
```

In `get_participant_state`, add to `state_msg` dict:
```python
"gdrive_url": misc_state.gdrive_url,
```

- [ ] **Step 4: Test — restart daemon, check participant state includes `gdrive_url`**

Run daemon, then: `curl -s http://localhost:1234/api/participant/state -H 'X-Participant-Id: test' | python3 -m json.tool | grep gdrive`
Expected: `"gdrive_url": "https://drive.google.com/drive/folders/..."` (or `null` if no session folder)

- [ ] **Step 5: Commit**

```bash
git add daemon/misc/state.py daemon/__main__.py daemon/participant/router.py
git commit -m "feat: resolve and serve Google Drive folder URL in participant state"
```

---

### Task 3: Add Google Drive icon to participant status bar

**Files:**
- Modify: `static/participant.html` — add icon button before Key Points
- Modify: `static/participant.js` — show/hide based on state, set href

- [ ] **Step 1: Add Google Drive icon button in `participant.html`**

Insert before the Key Points button (line 47), right after the notes button:

```html
<a id="gdrive-btn" class="header-link-btn" href="#" target="_blank" style="display:none; text-decoration:none;" title="Open session folder in Google Drive">
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 87.3 78" style="vertical-align:middle">
    <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
    <path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0-1.2 4.5h27.5z" fill="#00ac47"/>
    <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.85l5.85 10.15z" fill="#ea4335"/>
    <path d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.85 0H34.44c-1.65 0-3.2.45-4.55 1.2z" fill="#00832d"/>
    <path d="M59.85 53h27.45c0-1.55-.4-3.1-1.2-4.5L73.55 27.8c-.8-1.4-1.95-2.5-3.3-3.3L57.5 48.3z" fill="#2684fc"/>
    <path d="M43.65 25 30.9 1.2c-1.35.8-2.5 1.9-3.3 3.3L2.4 48.5c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#ffba00" style="display:none"/>
    <path d="m29.9 49.2 13.75 23.8 13.75-23.8z" fill="#ffba00" style="display:none"/>
    <path d="m27.6 53-13.75 23.8c1.35.8 2.9 1.2 4.55 1.2h50.9c1.65 0 3.2-.45 4.55-1.2L59.85 53z" fill="#ffba00"/>
  </svg>
</a>
```

- [ ] **Step 2: Handle `gdrive_url` in `participant.js` state handler**

Find where participant state is applied (the `handleStateMessage` or equivalent function that processes the REST `/api/participant/state` response). Add:

```javascript
// Google Drive link
const gdriveBtn = document.getElementById('gdrive-btn');
if (msg.gdrive_url) {
    gdriveBtn.href = msg.gdrive_url;
    gdriveBtn.style.display = '';
} else {
    gdriveBtn.style.display = 'none';
}
```

- [ ] **Step 3: Test visually**

Open participant page. Verify:
- Google Drive icon appears in status bar before Key Points when `gdrive_url` is set
- Clicking opens the Google Drive folder in a new tab
- Icon is hidden when no `gdrive_url`

- [ ] **Step 4: Commit and push**

```bash
git add static/participant.html static/participant.js
git commit -m "feat: show Google Drive folder link icon on participant status bar"
git push origin master
```
