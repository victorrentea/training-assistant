#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# start.sh — Unified launcher for all workshop companion processes
# ═══════════════════════════════════════════════════════════════════
#
# Starts two processes:
#   1. Training daemon  — polls server for quiz/debate/summary requests
#   2. Desktop overlay  — macOS overlay app rendering participant emoji reactions
#
# Auto-updates: every 2s, `git fetch` checks for new commits on master.
# When new code is detected (or daemon exits with code 42), the daemon is
# stopped, code is pulled, overlay is rebuilt, and the outer loop restarts both.
# The old overlay keeps running until the new instance self-replaces it via PID file.
#
# PREREQUISITES
#   - Python 3.12+ with project dependencies installed
#   - ~/.training-assistants-secrets.env with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER
#   - Swift toolchain (for desktop overlay)
#
# USAGE
#   ./start.sh                    # default server: https://interact.victorrentea.ro
#   ./start.sh ws://localhost:8000 # local dev server
#
# ═══════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/daemon/bash_log.sh"

OVERLAY_SERVER="${1:-wss://interact.victorrentea.ro}"
SECRETS_FILE="${TRAINING_ASSISTANTS_SECRETS_FILE:-$HOME/.training-assistants-secrets.env}"

# ── Preflight checks ──

if [ ! -f "$SECRETS_FILE" ]; then
  _log "start" "error" "$SECRETS_FILE not found — create with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER"
  exit 1
fi

if ! command -v swift &>/dev/null; then
  _log "start" "info" "Swift not found — desktop overlay will not start"
  NO_OVERLAY=1
fi

# ── PID tracking ──

DAEMON_PID=""
OVERLAY_PID=""

cleanup() {
  echo ""
  if [ -n "$DAEMON_PID" ]; then
    _log "start" "info" "💀 daemon (pid $DAEMON_PID)"
    kill "$DAEMON_PID" 2>/dev/null
    DAEMON_PID=""
  fi
  if [ -n "$OVERLAY_PID" ]; then
    _log "start" "info" "💀 overlay (pid $OVERLAY_PID)"
    kill "$OVERLAY_PID" 2>/dev/null
    OVERLAY_PID=""
  fi
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

# ── Build desktop overlay ──

build_overlay() {
  if [ -n "$NO_OVERLAY" ]; then return; fi
  _log "start" "info" "Building desktop overlay..."
  if (cd desktop-overlay && swift build 2>&1 | tail -1); then
    _log "start" "info" "Overlay built"
  else
    _log "start" "error" "Overlay build failed — skipping"
    NO_OVERLAY=1
  fi
}

# ── Process launchers ──

start_daemon() {
  _log "start" "info" "🚀 daemon starting..."
  python3 training_daemon.py &
  DAEMON_PID=$!
}

start_overlay() {
  if [ -n "$NO_OVERLAY" ]; then return; fi
  _log "start" "info" "🚀 overlay starting ($OVERLAY_SERVER)..."
  (cd desktop-overlay && .build/arm64-apple-macosx/debug/DesktopOverlay "$OVERLAY_SERVER") &
  OVERLAY_PID=$!
}

# ── Git auto-update (fallback when watcher unavailable) ──

LAST_KNOWN_REMOTE_HEAD=""

check_git_updates() {
  # Fetch quietly, compare origin/master before vs after fetch (branch-independent)
  git fetch origin master --quiet 2>/dev/null || return 1
  local new_remote_head
  new_remote_head=$(git rev-parse origin/master 2>/dev/null)
  [ -z "$new_remote_head" ] && return 1

  # Initialize on first call
  if [ -z "$LAST_KNOWN_REMOTE_HEAD" ]; then
    LAST_KNOWN_REMOTE_HEAD="$new_remote_head"
    return 1
  fi

  if [ "$new_remote_head" != "$LAST_KNOWN_REMOTE_HEAD" ]; then
    local msg
    msg=$(git log --oneline "$LAST_KNOWN_REMOTE_HEAD".."$new_remote_head" 2>/dev/null | head -3)
    _log "start" "info" "♻️  New commits — will restart: $msg"
    LAST_KNOWN_REMOTE_HEAD="$new_remote_head"
    return 0  # update available
  fi
  return 1  # no update
}

stop_all_processes() {
  if [ -n "$DAEMON_PID" ]; then
    _log "start" "info" "💀 daemon (pid $DAEMON_PID)"
    kill -9 "$DAEMON_PID" 2>/dev/null
    DAEMON_PID=""
  fi
  # Overlay is left running — the new instance will kill it on startup
}

pull_and_rebuild() {
  local new_commits
  new_commits=$(git log --oneline HEAD..origin/master 2>/dev/null)
  _log "start" "info" "⬇  Pulling: $new_commits"
  if ! git pull --ff-only 2>&1; then
    _log "start" "warn" "git pull failed — continuing with existing code"
  fi
  build_overlay
}

# ── Main loop ──

build_overlay

while true; do
  start_daemon
  start_overlay

  echo ""
  _log "start" "info" "🟢 daemon  🟢 overlay"
  echo ""

  # Poll loop: check daemon health + git updates every 10s
  RESTART_REASON=""
  GIT_CHECK_COUNTER=0
  while true; do
    sleep 0.5
    GIT_CHECK_COUNTER=$((GIT_CHECK_COUNTER + 1))

    # Check if daemon exited
    if [ -n "$DAEMON_PID" ] && ! kill -0 "$DAEMON_PID" 2>/dev/null; then
      wait "$DAEMON_PID" 2>/dev/null && DAEMON_EXIT=0 || DAEMON_EXIT=$?
      DAEMON_PID=""
      if [ $DAEMON_EXIT -eq 0 ]; then
        _log "start" "info" "🔴 daemon (clean exit)"
        stop_all_processes
        exit 0
      elif [ $DAEMON_EXIT -eq 42 ]; then
        RESTART_REASON="daemon-version-change"
        break
      else
        _log "start" "error" "🔴 daemon crashed (exit $DAEMON_EXIT)"
        RESTART_REASON="daemon-crash"
        break
      fi
    fi

    # Git-based update detection (every 2s)
    if [ $((GIT_CHECK_COUNTER % 4)) -eq 0 ]; then
      if check_git_updates; then
        RESTART_REASON="git-update"
        break
      fi
    fi
  done

  # Stop everything, update, and loop back to restart
  stop_all_processes
  pull_and_rebuild

  _log "start" "info" "♻️  Restarting (reason: $RESTART_REASON)..."
  echo ""
done
