# Deploy Countdown Notifications — Design Spec

## Summary

Enhance `watch-deploy.sh` to show a live countdown timer via a macOS menu bar item during deploys, with accurate SHA-based deploy detection and historical duration tracking.

## Problem

1. Current watcher notifies only on success or timeout — no visibility during deploy progress
2. Deploy detection uses version-change heuristic (`CURRENT_PROD != LAST_PROD_VERSION`) which breaks with overlapping pushes (push A deploys while tracking push B)
3. `terminal-notifier -group` flashes in/out on each update — distracting for frequent countdown updates

## Solution

### Menu Bar Countdown (JXA)

A `osascript -l JavaScript` process creates an `NSStatusItem` in the macOS menu bar. The bash script writes countdown text to `/tmp/deploy_status.txt`; the JXA process polls it every 0.5s and updates the menu bar item in-place. Zero animation, zero flash.

- **Idle state**: menu bar item hidden (or shows `🚀`)
- **During deploy**: `🚀 ~32s` → `🚀 ~25s` → `🚀 ~5s` → `🚀 ...` → hidden
- **JXA lifecycle**: launched when `watch-deploy.sh` starts, killed on cleanup

`terminal-notifier` is kept ONLY for final success/failure notifications (one-shot, flash is acceptable).

### SHA-Based Deploy Detection

Instead of checking "did version change?", extract the deployed commit SHA from `version.js` and compare it to the tracked `MERGE_SHA`.

Current `version.js` format: `const VERSION = '<timestamp>';`

**Problem**: `version.js` contains a timestamp, not a commit SHA. We need to change the approach:

The pre-commit hook stamps `version.js` with a timestamp. We can't easily map timestamp → commit SHA. Instead:

**Approach**: When a merge to master is detected, record the new master HEAD SHA. Then poll the production `version.js` — when the version string changes to something DIFFERENT from what it was when we started waiting, AND we're still tracking that same `MERGE_SHA`, we accept it. If a NEW push arrives (master HEAD changes again while waiting), we:
1. Reset `WAITING_SINCE` to now
2. Update `MERGE_SHA` to the new HEAD
3. Restart the countdown with fresh estimate
4. Do NOT record the interrupted deploy in history

This is already how the code works (line 217-228). The key fix is: **do not count a version change as "success" if master HEAD has moved again since we started waiting** — because that means a newer push superseded our tracked one, and the version change might be from the older push.

**Refined success condition**:
- Version changed AND `MERGE_SHA == LAST_MASTER_HEAD` (no newer push has arrived) → success, record duration
- Version changed AND `MERGE_SHA != LAST_MASTER_HEAD` → stale deploy from older push; update `LAST_PROD_VERSION` but do NOT declare success or record duration; keep waiting for the newer push

## Design

### Deploy History File

- **Location**: `deploy-history.txt` in the project directory (via `SCRIPT_DIR`)
- **Format**: one line per successful deploy — `<unix_timestamp> <duration_seconds>`
- **Retention**: last 20 entries (FIFO)
- **Estimation**: arithmetic mean of recorded durations
- **Fallback**: 45 seconds when file is empty or missing
- **Gitignored**: add to `.gitignore`

### JXA Menu Bar Script

File: `deploy-status-bar.js` (in project root, committed to repo)

```javascript
// osascript -l JavaScript deploy-status-bar.js
// Reads /tmp/deploy_status.txt every 0.5s, updates menu bar item
ObjC.import('Cocoa');
ObjC.import('Foundation');

// Create status bar item, poll file, update title
// When file is empty or missing → hide item
// When file has text → show item with that text
```

Communication protocol (via `/tmp/deploy_status.txt`):
- File contains the exact text to display (e.g., `🚀 ~32s`)
- Empty file or missing file → hide the status item
- `watch-deploy.sh` writes to this file; JXA reads it

### Countdown Flow

When a merge is detected:

1. **Write initial text**: `echo "🚀 ~42s" > /tmp/deploy_status.txt`
2. **Every 2s** (loop iteration): recalculate remaining, write updated text
   - `remaining > 5`: `🚀 ~25s`
   - `remaining ≤ 5`: `🚀 soon...`
   - `remaining ≤ 0`: `🚀 ...`
3. **On success**: clear file (`> /tmp/deploy_status.txt`), send `terminal-notifier` + Glass.aiff
4. **On timeout**: clear file, send `terminal-notifier` + Basso.aiff
5. **On new push while waiting**: reset countdown, write new initial text

### Changes to `watch-deploy.sh`

**New:**
- Launch JXA process on startup (`osascript -l JavaScript deploy-status-bar.js &`)
- Kill JXA process on cleanup (trap)
- `update_status_bar(text)` — writes to `/tmp/deploy_status.txt`
- `clear_status_bar()` — empties the file

**Modified:**
- Success detection: add `MERGE_SHA == LAST_MASTER_HEAD` check
- Countdown: write to status bar file instead of `terminal-notifier`
- `notify_countdown` removed (replaced by status bar writes)

**Unchanged:**
- 2s polling for `version.js`
- 10s polling for GitHub API
- Lock file / heartbeat
- `notify_success` / `notify_failure` (keep `terminal-notifier` for these)
- Deploy history file functions

### .gitignore Addition

Add `deploy-history.txt` to `.gitignore`.

## Out of Scope

- Swift compiled binaries
- Floating overlay windows
- Notification sounds during countdown (only at success/failure)
