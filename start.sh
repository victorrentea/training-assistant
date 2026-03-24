#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# start.sh — Unified launcher for all workshop companion processes
# ═══════════════════════════════════════════════════════════════════
#
# Starts three processes:
#   1. Training daemon  — polls server for quiz/debate/summary requests
#   2. Deploy watcher   — monitors production deploys, notifies on success/failure
#   3. Emoji overlay    — macOS overlay app rendering participant emoji reactions
#
# Auto-updates: every 10s, `git fetch` checks for new commits on master.
# When new code is detected (or daemon exits with code 42), ALL processes
# are stopped, code is pulled, overlay is rebuilt, and everything restarts.
#
# PREREQUISITES
#   - Python 3.12+ with project dependencies installed
#   - secrets.env with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER
#   - Swift toolchain (for emoji overlay)
#   - gh CLI authenticated (for deploy watcher)
#
# USAGE
#   ./start.sh                    # default server: https://interact.victorrentea.ro
#   ./start.sh ws://localhost:8000 # local dev server
#
# ═══════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

OVERLAY_SERVER="${1:-wss://interact.victorrentea.ro}"

# ── Preflight checks ──

if [ ! -f secrets.env ]; then
  echo "❌ secrets.env not found. Create it with at least ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER."
  exit 1
fi

if ! command -v swift &>/dev/null; then
  echo "⚠️  Swift not found — emoji overlay will not start."
  NO_OVERLAY=1
fi

if ! command -v gh &>/dev/null; then
  echo "⚠️  gh CLI not found — deploy watcher will not start."
  NO_WATCHER=1
fi

# ── PID tracking ──

DAEMON_PID=""
WATCHER_PID=""
OVERLAY_PID=""

cleanup() {
  echo ""
  echo "$(date '+%H:%M:%S') 🛑 Shutting down all processes..."
  [ -n "$DAEMON_PID" ]  && kill "$DAEMON_PID"  2>/dev/null
  [ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null
  [ -n "$OVERLAY_PID" ] && kill "$OVERLAY_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

# ── Build emoji overlay ──

build_overlay() {
  if [ -n "$NO_OVERLAY" ]; then return; fi
  echo "$(date '+%H:%M:%S') 🔨 Building emoji overlay..."
  if (cd emoji-overlay && swift build 2>&1 | tail -1); then
    echo "$(date '+%H:%M:%S') ✅ Overlay built."
  else
    echo "$(date '+%H:%M:%S') ⚠️  Overlay build failed — skipping."
    NO_OVERLAY=1
  fi
}

# ── Process launchers ──

start_daemon() {
  echo "$(date '+%H:%M:%S') 🚀 Starting training daemon..."
  python3 training_daemon.py &
  DAEMON_PID=$!
}

start_watcher() {
  if [ -n "$NO_WATCHER" ]; then return; fi
  kill_old_watcher
  echo "$(date '+%H:%M:%S') 👀 Starting deploy watcher..."
  bash -c '
    REPO="victorrentea/training-assistant"
    PROD_URL="https://interact.victorrentea.ro/static/version.js"
    DEPLOY_TIMEOUT=120
    SCRIPT_DIR="'"$SCRIPT_DIR"'"
    HISTORY_FILE="$SCRIPT_DIR/deploy-history.txt"
    DEFAULT_ESTIMATE=45

    get_prod_version() { curl -s "$PROD_URL" | grep -o "'"'"'.*'"'"'" | tr -d "'"'"'"; }
    get_master_head() { gh api "repos/$REPO/commits/master" --jq ".sha" 2>/dev/null; }
    get_commit_message() { gh api "repos/$REPO/commits/$1" --jq ".commit.message" 2>/dev/null | head -1; }

    get_estimated_duration() {
      if [ ! -f "$HISTORY_FILE" ] || [ ! -s "$HISTORY_FILE" ]; then echo "$DEFAULT_ESTIMATE"; return; fi
      local sum=0 count=0 dur
      while read -r _ts dur; do [ -n "$dur" ] && sum=$((sum + dur)) && count=$((count + 1)); done < "$HISTORY_FILE"
      [ "$count" -eq 0 ] && echo "$DEFAULT_ESTIMATE" || echo $((sum / count))
    }

    record_deploy() { echo "$(date +%s) $1" >> "$HISTORY_FILE"; tail -n 20 "$HISTORY_FILE" > "$HISTORY_FILE.tmp" && mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"; }

    LOCK_FILE="/tmp/watch_deploy.lock"
    echo "{\"pid\": $$, \"heartbeat\": $(date +%s)}" > "$LOCK_FILE"
    trap "rm -f $LOCK_FILE; exit 0" INT TERM

    LAST_MASTER_HEAD=$(get_master_head)
    LAST_PROD_VERSION=$(get_prod_version)
    WAITING_SINCE="" MERGE_SHA="" ESTIMATED="" COMMIT_MSG=""
    NOTIFY_INTERVAL=5 LAST_NOTIFY_TIME=0 LAST_NOTIFY_TITLE=""
    POLL_COUNTER=0

    echo "$(date '"'"'+%H:%M:%S'"'"') 👀 Watching deploys... (PID $$)"
    echo "  Master HEAD: ${LAST_MASTER_HEAD:0:8}"
    echo "  Production:  $LAST_PROD_VERSION"

    while true; do
      sleep 2
      POLL_COUNTER=$((POLL_COUNTER + 1))
      [ $((POLL_COUNTER % 5)) -eq 0 ] && echo "{\"pid\": $$, \"heartbeat\": $(date +%s)}" > "$LOCK_FILE"

      CURRENT_PROD=$(get_prod_version)

      if [ -n "$WAITING_SINCE" ]; then
        NOW=$(date +%s); ELAPSED=$((NOW - WAITING_SINCE))
        if [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
          record_deploy "$ELAPSED"
          echo "$(date '"'"'+%H:%M:%S'"'"') ✅ Deployed! Version: $CURRENT_PROD"
          terminal-notifier -title "🚀 Deployed!" -message "$COMMIT_MSG" -group deploy -timeout 5 &>/dev/null &
          afplay /System/Library/Sounds/Glass.aiff & sleep 0.4; afplay /System/Library/Sounds/Glass.aiff
          LAST_PROD_VERSION="$CURRENT_PROD"; WAITING_SINCE=""; MERGE_SHA=""; ESTIMATED=""; COMMIT_MSG=""
          continue
        fi
        if [ "$ELAPSED" -ge "$DEPLOY_TIMEOUT" ]; then
          echo "$(date '"'"'+%H:%M:%S'"'"') ❌ Deploy timeout! ${MERGE_SHA:0:8} not deployed after ${DEPLOY_TIMEOUT}s"
          terminal-notifier -title "❌ Deploy Timeout!" -message "Merge ${MERGE_SHA:0:8} not deployed after ${DEPLOY_TIMEOUT}s" -group deploy -timeout 10 &>/dev/null &
          # sound removed — only success deploy gets audio
          LAST_PROD_VERSION="$CURRENT_PROD"; WAITING_SINCE=""; MERGE_SHA=""; ESTIMATED=""; COMMIT_MSG=""
          continue
        fi
        REMAINING=$((ESTIMATED - ELAPSED))
        NOW_S=$(date +%s)
        if [ $((NOW_S - LAST_NOTIFY_TIME)) -ge "$NOTIFY_INTERVAL" ]; then
          TITLE="🚀 Deploying in about ${REMAINING}s"
          [ "$REMAINING" -le 5 ] && TITLE="🚀 Deploying any moment..."
          if [ "$TITLE" != "$LAST_NOTIFY_TITLE" ]; then
            LAST_NOTIFY_TIME="$NOW_S"; LAST_NOTIFY_TITLE="$TITLE"
            terminal-notifier -title "$TITLE" -message "$COMMIT_MSG" -group deploy &>/dev/null &
          fi
        fi
      else
        [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ] && echo "$(date '"'"'+%H:%M:%S'"'"') 🔄 Production version changed: $CURRENT_PROD" && LAST_PROD_VERSION="$CURRENT_PROD"
      fi

      if [ $((POLL_COUNTER % 5)) -eq 0 ]; then
        CURRENT_HEAD=$(get_master_head)
        if [ -n "$CURRENT_HEAD" ] && [ "$CURRENT_HEAD" != "$LAST_MASTER_HEAD" ]; then
          COMMIT_MSG=$(get_commit_message "$CURRENT_HEAD")
          LAST_MASTER_HEAD="$CURRENT_HEAD"; MERGE_SHA="$CURRENT_HEAD"
          if [ -z "$WAITING_SINCE" ]; then
            ESTIMATED=$(get_estimated_duration); WAITING_SINCE=$(date +%s)
            echo "$(date '"'"'+%H:%M:%S'"'"') 🔀 Merge detected! HEAD: ${CURRENT_HEAD:0:8} — $COMMIT_MSG (~${ESTIMATED}s)"
          else
            echo "$(date '"'"'+%H:%M:%S'"'"') 🔀 New push while waiting! HEAD: ${CURRENT_HEAD:0:8} — $COMMIT_MSG"
          fi
          LAST_NOTIFY_TIME=0; LAST_NOTIFY_TITLE=""
        elif [ -n "$CURRENT_HEAD" ]; then
          LAST_MASTER_HEAD="$CURRENT_HEAD"
        fi
      fi
    done
  ' &
  WATCHER_PID=$!
}

kill_old_watcher() {
  local lock_file="/tmp/watch_deploy.lock"
  if [ -f "$lock_file" ]; then
    local old_pid
    old_pid=$(python3 -c "import json,sys; print(json.load(sys.stdin).get('pid',''))" < "$lock_file" 2>/dev/null)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      echo "$(date '+%H:%M:%S') 🔪 Killing old deploy watcher (PID $old_pid)..."
      kill "$old_pid" 2>/dev/null
      for i in 1 2 3; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 1
      done
      kill -0 "$old_pid" 2>/dev/null && kill -9 "$old_pid" 2>/dev/null
    fi
    rm -f "$lock_file"
  fi
}

kill_old_overlay() {
  local pid_file="/tmp/emoji-overlay.pid"
  if [ -f "$pid_file" ]; then
    local old_pid
    old_pid=$(cat "$pid_file" 2>/dev/null)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      echo "$(date '+%H:%M:%S') 🔪 Killing old emoji overlay (PID $old_pid)..."
      kill "$old_pid" 2>/dev/null
      # Wait up to 3s for it to exit
      for i in 1 2 3; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 1
      done
      # Force kill if still alive
      kill -0 "$old_pid" 2>/dev/null && kill -9 "$old_pid" 2>/dev/null
    fi
    rm -f "$pid_file"
  fi
}

start_overlay() {
  if [ -n "$NO_OVERLAY" ]; then return; fi
  kill_old_overlay
  echo "$(date '+%H:%M:%S') 🎨 Starting emoji overlay (server: $OVERLAY_SERVER)..."
  (cd emoji-overlay && .build/arm64-apple-macosx/debug/EmojiOverlay "$OVERLAY_SERVER") &
  OVERLAY_PID=$!
}

# ── Git auto-update ──

GIT_POLL_INTERVAL=2  # seconds between git fetch checks
LOCAL_HEAD=""

check_git_updates() {
  # Fetch quietly, compare local master vs origin/master
  git fetch origin master --quiet 2>/dev/null || return 1
  local remote_head
  remote_head=$(git rev-parse origin/master 2>/dev/null)
  local local_head
  local_head=$(git rev-parse HEAD 2>/dev/null)

  if [ -n "$remote_head" ] && [ "$remote_head" != "$local_head" ]; then
    local msg
    msg=$(git log --oneline "$local_head".."$remote_head" 2>/dev/null | head -3)
    echo ""
    echo "$(date '+%H:%M:%S') 🔀 New commits on master detected!"
    echo "$msg"
    return 0  # update available
  fi
  return 1  # no update
}

stop_all_processes() {
  echo "$(date '+%H:%M:%S') 🛑 Stopping all processes..."
  [ -n "$DAEMON_PID" ]  && kill "$DAEMON_PID"  2>/dev/null && DAEMON_PID=""
  [ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null && WATCHER_PID=""
  [ -n "$OVERLAY_PID" ] && kill "$OVERLAY_PID" 2>/dev/null && OVERLAY_PID=""
  wait 2>/dev/null
}

pull_and_rebuild() {
  echo "$(date '+%H:%M:%S') 📥 Pulling latest code..."
  if ! git pull; then
    echo "❌ git pull failed. Please resolve manually."
    exit 1
  fi
  echo "$(date '+%H:%M:%S') 🔨 Rebuilding..."
  build_overlay
}

# ── Main loop ──

build_overlay

while true; do
  start_daemon
  start_watcher
  start_overlay

  echo ""
  echo "$(date '+%H:%M:%S') ✅ All processes running."
  echo "  Training daemon: PID $DAEMON_PID"
  [ -n "$WATCHER_PID" ] && echo "  Deploy watcher:  PID $WATCHER_PID"
  [ -n "$OVERLAY_PID" ] && echo "  Emoji overlay:   PID $OVERLAY_PID"
  echo ""

  # Poll loop: check daemon health + git updates
  RESTART_REASON=""
  while true; do
    sleep "$GIT_POLL_INTERVAL"

    # Check if daemon exited
    if [ -n "$DAEMON_PID" ] && ! kill -0 "$DAEMON_PID" 2>/dev/null; then
      wait "$DAEMON_PID" 2>/dev/null
      DAEMON_EXIT=$?
      DAEMON_PID=""
      if [ $DAEMON_EXIT -eq 0 ]; then
        echo "$(date '+%H:%M:%S') 👋 Daemon stopped normally. Shutting down."
        stop_all_processes
        exit 0
      elif [ $DAEMON_EXIT -eq 42 ]; then
        RESTART_REASON="daemon-version-change"
        break
      else
        echo "$(date '+%H:%M:%S') ⚠️  Daemon crashed (exit $DAEMON_EXIT) — will restart after pull check"
        RESTART_REASON="daemon-crash"
        break
      fi
    fi

    # Check for new commits on origin/master
    if check_git_updates; then
      RESTART_REASON="git-update"
      break
    fi
  done

  # Stop everything and update
  stop_all_processes
  pull_and_rebuild

  echo "$(date '+%H:%M:%S') 🔁 Restarting all processes (reason: $RESTART_REASON)..."
  echo ""
done
