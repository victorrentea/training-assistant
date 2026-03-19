# Session Notes Integration — Design Spec

**Date:** 2026-03-19
**Status:** Approved

---

## Goal

The quiz daemon automatically finds the trainer's session notes folder for today's date, reads the notes file inside it, and injects those notes into every LLM quiz-generation prompt as a high-weight primary source. The host UI shows whether the folder and notes were found, via the existing Agent badge.

---

## 1. Session Folder Detection (`quiz_core.py`)

### Configuration

New env var: `SESSIONS_FOLDER` (default: `~/My Drive/Cursuri/###sesiuni`).

### Matching logic

Scan all subdirectories of `SESSIONS_FOLDER`. For each, parse the name with a regex to extract a date range. A folder matches if today's date falls within that range (inclusive).

Folder name patterns to support:
- `YYYY-MM-DD Topic@Client` — single day
- `YYYY-MM-DD..DD Topic@Client` — same month, multiple days
- `YYYY-MM-DD..MM-DD Topic@Client` — cross-month range (same year)

### Notes file

Within the matched folder, look for any `.txt` file. If multiple exist, use the most recently modified. Store both paths on `Config`:

```python
session_folder: Optional[Path] = None   # matched folder path
session_notes:  Optional[Path] = None   # notes .txt file path, if found
```

### Outcomes

| Condition | `session_folder` | `session_notes` |
|---|---|---|
| Folder + notes found | set | set |
| Folder found, no .txt | set | None |
| No matching folder | None | None |

---

## 2. Notes in Quiz Generation (`quiz_core.py`)

When `config.session_notes` is set, read the file in full (no time-windowing). Inject as a clearly labeled section in the LLM prompt, before the transcript:

```
SESSION NOTES (trainer's written agenda/key points — treat as primary source):
<notes content>

TRANSCRIPT EXCERPT (last N min of live audio — use for context and recent topics):
<transcript content>
```

When generating from a topic (RAG path), notes are also included alongside RAG results.

If the notes file cannot be read (permissions, encoding error), log a warning and continue without them — never block quiz generation.

---

## 3. Daemon Startup & Re-detection (`quiz_daemon.py`)

- At startup: call `find_session_folder(date.today())`, update `Config` via `dataclasses.replace()`, log result.
- On each poll cycle: if calendar date has changed since last detection, re-run detection. This handles multi-day workshops where the daemon runs overnight.
- Extend the daemon status payload with two new fields:
  - `session_folder`: basename of matched folder, or `null`
  - `session_notes`: filename of notes file, or `null`

The server forwards these fields unchanged in the daemon status broadcast to the host UI.

---

## 4. Host UI (`host.html` / `host.js`)

The existing "Agent" badge in the bottom-left status bar is extended:

| State | Badge color | Tooltip |
|---|---|---|
| Daemon connected, folder + notes found | green | `2026-03-19 Microservices@accenture` |
| Daemon connected, folder found, no notes | orange | `Session folder found but no notes file` |
| Daemon connected, no folder found | orange | `No session folder found for today` |
| Daemon disconnected | grey (unchanged) | (existing behaviour) |

Tooltip is set via the `title` attribute on the badge element — no new UI elements.

---

## Files Changed

| File | Change |
|---|---|
| `quiz_core.py` | Add `session_folder`/`session_notes` to `Config`; add `find_session_folder()`; inject notes into prompt |
| `quiz_daemon.py` | Call `find_session_folder()` at startup; re-detect on date change; extend status payload |
| `routers/quiz.py` or `main.py` | Forward `session_folder`/`session_notes` in daemon status broadcast |
| `static/host.js` | Update Agent badge color/tooltip based on session fields |

---

## Out of Scope

- Watching the notes file for live changes (notes are read fresh on each generation)
- Multi-folder support (at most one session per day)
- Surfacing notes content directly in the host UI
