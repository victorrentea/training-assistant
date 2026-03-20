# Daemon Auto-Update Design

## Problem

When the server gets a new deployment (push to master → Railway deploys), the local quiz daemon still runs old code. The trainer must manually `git pull` and restart the daemon.

## Solution

The daemon detects server version changes and exits with a special code. The start script loops and handles the update.

## Changes

### `quiz_core.py`

- Change `DAEMON_POLL_INTERVAL` from `1` to `3` seconds.

### `quiz_daemon.py`

- On startup, fetch `backend_version` from `/api/status` (public endpoint, no auth needed) and store as `_startup_version`.
- In the main loop, fetch `/api/status` each cycle and compare `backend_version` to `_startup_version`.
- If version changed: log a message, clean up lock file, `sys.exit(42)`.
- Exit code `42` means "update available — please pull and restart".

### `start-daemon.sh`

- Wrap `python3 quiz_daemon.py` in a loop.
- After daemon exits:
  - Exit code `42`: run `git pull origin master`, then restart the loop.
  - Exit code `0`: normal shutdown, exit the script.
  - Any other code: log error, exit the script (don't restart on crashes).

## Sequence

```
start-daemon.sh
  └─ loop:
       ├─ python3 quiz_daemon.py
       │    ├─ startup: GET /api/status → save backend_version
       │    ├─ every 3s: GET /api/status → compare
       │    └─ version changed? → cleanup → sys.exit(42)
       ├─ exit 42? → git pull origin master → continue loop
       ├─ exit 0?  → break (normal stop)
       └─ other?   → break (error)
```

## Edge Cases

- Server unreachable at startup: daemon starts anyway, skips version check until server is reachable.
- Server unreachable during loop: existing error handling catches it; version check skipped that cycle.
- `git pull` conflicts: script logs the error and exits (manual intervention needed).
