#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# start.sh — Launcher for the training daemon
# ═══════════════════════════════════════════════════════════════════
#
# Starts the training daemon which polls the Railway backend for
# quiz/debate/summary requests.
#
# NOTE: Desktop overlay has moved to victor-macos-addons repo.
# NOTE: Wispr cleanup (wispr-addons/app.py) is NOT started here — run it separately.
#
# Auto-updates: every 2s, `git fetch` checks for new commits on master.
# When new code is detected (or daemon exits with code 42), the daemon is
# stopped, code is pulled, and the outer loop restarts it.
#
# PREREQUISITES
#   - Python 3.12+ with project dependencies installed
#   - ~/.training-assistants-secrets.env with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER
#
# USAGE
#   ./start.sh
#
# ═══════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/daemon/bash_log.sh"

EXIT_REASON=""
_on_exit() {
  [ -n "$EXIT_REASON" ] && _log "start" "info" "💥 $EXIT_REASON"
}
trap _on_exit EXIT

SECRETS_FILE="${TRAINING_ASSISTANTS_SECRETS_FILE:-$HOME/.training-assistants-secrets.env}"

# ── Preflight checks ──

if [ ! -f "$SECRETS_FILE" ]; then
  _log "start" "error" "$SECRETS_FILE not found — create with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER"
  EXIT_REASON="secrets file not found: $SECRETS_FILE"
  exit 1
fi

# ── PID tracking ──

DAEMON_PID=""

cleanup() {
  echo ""
  if [ -n "$DAEMON_PID" ]; then
    _log "start" "info" "💀 daemon (pid $DAEMON_PID)"
    kill "$DAEMON_PID" 2>/dev/null || true
    DAEMON_PID=""
  fi
  wait 2>/dev/null || true
  EXIT_REASON="interrupted (SIGINT/SIGTERM)"
  exit 0
}
trap cleanup INT TERM

# ── Process launcher ──

start_daemon() {
  python3 -m daemon &
  DAEMON_PID=$!
}

# ── Git auto-update ──

LAST_KNOWN_REMOTE_HEAD=""

check_git_updates() {
  git fetch origin master --quiet 2>/dev/null || return 1
  local new_remote_head
  new_remote_head=$(git rev-parse origin/master 2>/dev/null)
  [ -z "$new_remote_head" ] && return 1

  if [ -z "$LAST_KNOWN_REMOTE_HEAD" ]; then
    LAST_KNOWN_REMOTE_HEAD="$new_remote_head"
    return 1
  fi

  if [ "$new_remote_head" != "$LAST_KNOWN_REMOTE_HEAD" ]; then
    local msg
    msg=$(git log --oneline "$LAST_KNOWN_REMOTE_HEAD".."$new_remote_head" 2>/dev/null | head -3)
    _log "start" "info" "♻️  New commits — will restart: $msg"
    LAST_KNOWN_REMOTE_HEAD="$new_remote_head"
    return 0
  fi
  return 1
}

stop_all_processes() {
  if [ -n "$DAEMON_PID" ]; then
    _log "start" "info" "💀 daemon (pid $DAEMON_PID)"
    kill -9 "$DAEMON_PID" 2>/dev/null || true
    DAEMON_PID=""
  fi
}

pull_and_rebuild() {
  local new_commits
  new_commits=$(git log --oneline HEAD..origin/master 2>/dev/null)
  _log "start" "info" "⬇  Pulling: $new_commits"
  if ! git pull --ff-only 2>&1; then
    _log "start" "warn" "git pull failed — continuing with existing code"
  fi
}

# ── Main loop ──

while true; do
  start_daemon

  echo ""
  _log "start" "info" "🟢 daemon"
  echo ""

  RESTART_REASON=""
  GIT_CHECK_COUNTER=0
  while true; do
    sleep 0.5
    GIT_CHECK_COUNTER=$((GIT_CHECK_COUNTER + 1))

    if [ -n "$DAEMON_PID" ] && ! kill -0 "$DAEMON_PID" 2>/dev/null; then
      wait "$DAEMON_PID" 2>/dev/null && DAEMON_EXIT=0 || DAEMON_EXIT=$?
      DAEMON_PID=""
      if [ $DAEMON_EXIT -eq 0 ]; then
        _log "start" "info" "🔴 daemon (clean exit) — restarting in 3s"
        afplay /System/Library/Sounds/Sosumi.aiff &
        sleep 3
        RESTART_REASON="daemon-clean-exit"
        break
      elif [ $DAEMON_EXIT -eq 42 ]; then
        RESTART_REASON="daemon-version-change"
        break
      else
        _log "start" "error" "🔴 daemon crashed (exit $DAEMON_EXIT)"
        RESTART_REASON="daemon-crash"
        break
      fi
    fi

    if [ $((GIT_CHECK_COUNTER % 4)) -eq 0 ]; then
      if check_git_updates; then
        RESTART_REASON="git-update"
        break
      fi
    fi
  done

  stop_all_processes
  pull_and_rebuild

  _log "start" "info" "♻️  Restarting (reason: $RESTART_REASON)..."
  echo ""
done
