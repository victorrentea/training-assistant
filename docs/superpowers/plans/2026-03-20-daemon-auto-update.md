# Daemon Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Daemon detects server version changes and auto-restarts with fresh code via `git pull`.

**Architecture:** Daemon fetches `/api/status` each poll cycle, compares `backend_version` to the version seen at startup. On mismatch, exits with code 42. Shell wrapper loops: on exit 42, runs `git pull` and restarts; on exit 0, stops; on other codes, stops with error.

**Tech Stack:** Python 3.12, Bash

**Spec:** `docs/superpowers/specs/2026-03-20-daemon-auto-update-design.md`

---

### Task 1: Change poll interval to 3 seconds

**Files:**
- Modify: `quiz_core.py:30`

- [ ] **Step 1: Change DAEMON_POLL_INTERVAL**

```python
# Line 30, change from:
DAEMON_POLL_INTERVAL = 1  # seconds
# to:
DAEMON_POLL_INTERVAL = 3  # seconds
```

- [ ] **Step 2: Commit**

```bash
git add quiz_core.py
git commit -m "chore: increase daemon poll interval to 3 seconds"
```

---

### Task 2: Add version check to daemon

**Files:**
- Modify: `quiz_daemon.py`

- [ ] **Step 1: Add exit code constant and version fetch helper**

At the top of `quiz_daemon.py`, after the existing constants (around line 40), add:

```python
EXIT_CODE_UPDATE = 42  # signals start-daemon.sh to git pull and restart
```

- [ ] **Step 2: Add startup version fetch**

In the `run()` function, after `config = config_from_env()` (line 188) and before the session folder detection, add:

```python
# ── Fetch server version at startup for auto-update detection ──
_startup_version = None
try:
    status = _get_json(f"{config.server_url}/api/status")
    _startup_version = status.get("backend_version")
    if _startup_version:
        print(f"[daemon] Server version at startup: {_startup_version}")
    else:
        print("[daemon] Warning: server /api/status did not return backend_version", file=sys.stderr)
except RuntimeError as e:
    print(f"[daemon] Warning: could not fetch server version at startup: {e}", file=sys.stderr)
```

- [ ] **Step 3: Add version check in the main loop**

Inside the `while True` loop, after the existing `try:` block opens and the heartbeat/timestamp logic, but **before** the quiz-request check (before line 261), add:

```python
# ── Auto-update: check if server version changed ──
if _startup_version:
    try:
        status = _get_json(f"{config.server_url}/api/status")
        current_version = status.get("backend_version")
        if current_version and current_version != _startup_version:
            print(f"\n[daemon] Server version changed: {_startup_version} → {current_version}")
            print("[daemon] Exiting for auto-update (exit code 42)...")
            _LOCK_FILE.unlink(missing_ok=True)
            sys.exit(EXIT_CODE_UPDATE)
    except RuntimeError:
        pass  # server unreachable — skip version check this cycle
```

- [ ] **Step 4: Verify daemon starts and runs normally**

```bash
python3 quiz_daemon.py
# Should print: [daemon] Server version at startup: <version>
# Ctrl+C to stop
```

- [ ] **Step 5: Commit**

```bash
git add quiz_daemon.py
git commit -m "feat: daemon detects server version change and exits with code 42"
```

---

### Task 3: Update start-daemon.sh with restart loop

**Files:**
- Modify: `start-daemon.sh`

- [ ] **Step 1: Replace the script content**

Replace the last two lines (`echo "🚀 Starting quiz daemon..."` and `python3 quiz_daemon.py`) with:

```bash
while true; do
  echo "🚀 Starting quiz daemon..."
  python3 quiz_daemon.py
  exit_code=$?

  if [ $exit_code -eq 42 ]; then
    echo ""
    echo "🔄 Server version changed — pulling latest code..."
    if ! git pull; then
      echo "❌ git pull failed. Please resolve manually."
      exit 1
    fi
    echo "✅ Code updated. Restarting daemon..."
    echo ""
    continue
  elif [ $exit_code -eq 0 ]; then
    echo "👋 Daemon stopped normally."
    exit 0
  else
    echo "❌ Daemon exited with error code $exit_code."
    exit $exit_code
  fi
done
```

- [ ] **Step 2: Test the script manually**

```bash
./start-daemon.sh
# Should start daemon normally
# Ctrl+C → should print "Daemon stopped normally." and exit
```

- [ ] **Step 3: Commit**

```bash
git add start-daemon.sh
git commit -m "feat: start-daemon.sh loops with git pull on version change"
```
