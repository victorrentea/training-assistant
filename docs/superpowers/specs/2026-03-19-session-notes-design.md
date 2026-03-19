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

If `SESSIONS_FOLDER` does not exist or is not a directory: log a warning and set `session_folder = None` — the daemon continues running normally, the badge shows no folder. This is a soft failure (unlike `TRANSCRIPTION_FOLDER` which is required).

### Matching logic

Scan all subdirectories of `SESSIONS_FOLDER`. For each, attempt to parse the name with this regex (using `re.match`):

```
^(\d{4}-\d{2}-\d{2})(?:\.\.(\d{2}(?:-\d{2})?))?[\s_]
```

- Group 1: start date `YYYY-MM-DD`
- Group 2 (optional): end suffix — contains a hyphen → treat as `MM-DD` (cross-month); no hyphen → treat as `DD` (same month)
- The separator character (`[\s_]`) is required but its value is not captured; anything (including nothing) may follow it

Non-matching folder names are silently skipped.

End date construction:
- No group 2 → single day, `end = start`
- Group 2 has no hyphen (`DD`) → `end = date(start.year, start.month, int(DD))`
- Group 2 has hyphen (`MM-DD`) → `end = date(start.year, int(MM), int(DD))`

If constructing the end date raises `ValueError` (invalid calendar date) or produces `end < start`, skip the folder silently and log a debug message.

Year boundaries (e.g. Dec–Jan) are not supported; such folders produce `end < start` and are skipped.

A folder matches if `start_date <= today <= end_date`.

**Multiple matches:** If more than one folder matches today, use the one with the latest `start_date`. In case of equal start dates, use the alphabetically last folder name. Log a warning listing all matches.

### Return signature

```python
def find_session_folder(today: date) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (session_folder, session_notes). Both None if not found."""
```

Callers use: `config = dataclasses.replace(config, session_folder=sf, session_notes=sn)`

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
| `SESSIONS_FOLDER` missing | None | None |

---

## 2. Notes in Quiz Generation (`quiz_core.py`)

Notes are read by the **callers** of `generate_quiz` (`auto_generate` and `auto_generate_topic`), not inside `generate_quiz` itself. This keeps `generate_quiz` free of I/O side effects. A new helper `read_session_notes(config) -> str` reads and returns the notes content (or `""` on failure).

Notes are read using UTF-8 encoding with `errors="replace"` (same as transcription files). Capped at 20,000 characters — truncated from the **start** (discard oldest content, keep the most recent). Truncation is logged as a warning. Read failure (permissions, encoding) logs a warning and returns `""`.

**Transcript path** (`auto_generate`): assemble `prompt_content` before calling `generate_quiz`:

```
SESSION NOTES (trainer's written agenda/key points — treat as primary source):
<notes_content>

TRANSCRIPT EXCERPT (last N min of live audio — use for context and recent topics):
<transcript_content>
```

- If `notes_content` is empty, omit the `SESSION NOTES` section.
- If `transcript_content` is empty but notes are present, omit the `TRANSCRIPT EXCERPT` section (notes-only prompt).
- If both are empty, call `post_status("error", "No transcript or session notes available.", config)` and return.

**Topic/RAG path** (`auto_generate_topic`): assemble `prompt_content` before calling `generate_quiz`:

```
TOPIC: <topic>

SESSION NOTES (trainer's written agenda/key points — treat as primary source):
<notes_content>
```

- If `notes_content` is empty, omit the `SESSION NOTES` section (existing behaviour unchanged).
- The transcript is not included for topic-based generation (existing behaviour).
- RAG results are appended by the existing `search_materials` tool call mechanism.

---

## 3. Daemon Startup & Re-detection (`quiz_daemon.py`)

- At startup: call `find_session_folder(date.today())`, update `config` via `dataclasses.replace()` and reassign: `config = dataclasses.replace(config, session_folder=sf, session_notes=sn)`. Log result (folder found / not found / no notes).
- Re-detection: a local variable `last_detected_date: Optional[date] = None` in the `run()` loop tracks when detection last ran. At the top of every poll cycle, if `date.today() != last_detected_date`, re-run `find_session_folder()` and reassign `config`. Re-detection is fast (filesystem scan only) — no loading state needed in the UI.
- Extend the daemon status payload with two new fields that are **always present** (even as `null`), so the host UI can distinguish "daemon connected, no folder" from "old daemon that doesn't send these fields":
  - `session_folder`: `Path(config.session_folder).name` or `null`
  - `session_notes`: `Path(config.session_notes).name` or `null`

**Where to add these fields:** `state.py` gets two new fields `daemon_session_folder: Optional[str] = None` and `daemon_session_notes: Optional[str] = None`. `POST /api/quiz-status` (`routers/quiz.py`, `update_quiz_status`) is extended to accept and store these fields. `build_state_message()` in `messaging.py` includes them in the WebSocket broadcast (alongside the existing `daemon_connected` / `daemon_last_seen`). The host UI treats absent fields (old daemon format) the same as `null`.

---

## 4. Host UI (`host.html` / `host.js`)

The existing "Agent" badge in the bottom-left status bar is extended:

| State | Badge color | Tooltip (`title` attribute) |
|---|---|---|
| Daemon connected, folder + notes found | green | basename of `session_folder` (e.g. `2026-03-19 Microservices@accenture`) |
| Daemon connected, folder found, no notes | orange | `Session folder found but no notes file` |
| Daemon connected, no folder found | orange | `No session folder found for today` |
| Daemon disconnected | grey (unchanged) | existing behaviour |

Tooltip is set via the `title` attribute on the badge element — no new UI elements.

---

## Files Changed

| File | Change |
|---|---|
| `quiz_core.py` | Add `session_folder`/`session_notes` to `Config`; add `find_session_folder()` and `read_session_notes()`; update `auto_generate` and `auto_generate_topic` to inject notes |
| `quiz_daemon.py` | Call `find_session_folder()` at startup; re-detect on date change; include `session_folder`/`session_notes` in `POST /api/quiz-status` payload |
| `state.py` | Add `daemon_session_folder: Optional[str]` and `daemon_session_notes: Optional[str]` |
| `routers/quiz.py` | `update_quiz_status` accepts and stores new fields |
| `messaging.py` | `build_state_message()` includes `daemon_session_folder` and `daemon_session_notes` |
| `static/host.js` | Update Agent badge color/tooltip based on session fields |

---

## Out of Scope

- Watching the notes file for live changes (notes are read fresh on each generation)
- Surfacing notes content directly in the host UI
- Year-boundary date ranges (e.g. Dec–Jan workshops)
