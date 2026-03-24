#!/bin/bash
# watch-deploy.sh — Continuous deploy watcher
#
# Detects new pushes to master (via GitHub API, every 10s) and
# waits for production to reflect the new version (polling every 2s).
# Notifies via terminal-notifier + sound on success/failure.
#
# USAGE
#   ./watch-deploy.sh        # foreground
#   ./watch-deploy.sh &      # background (typical)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/daemon/bash_log.sh"

REPO="victorrentea/training-assistant"
PROD_URL="https://interact.victorrentea.ro/static/version.js"
DEPLOY_TIMEOUT=120  # seconds to wait for production after a merge
HISTORY_FILE="$SCRIPT_DIR/deploy-history.txt"

get_prod_version() {
  curl -s "$PROD_URL" | grep -o "'.*'" | tr -d "'"
}

get_master_head() {
  gh api "repos/$REPO/commits/master" --jq '.sha' 2>/dev/null
}

notify_success() {
  local version="$1"
  _log "watcher" "info" "Deployed! Version: $version"
  echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ $version" >> "$HISTORY_FILE"
  terminal-notifier -title "🚀 Deployed!" -message "Version $version is live" -timeout 5 &
  afplay /System/Library/Sounds/Glass.aiff &
  sleep 0.4
  afplay /System/Library/Sounds/Glass.aiff
}

notify_failure() {
  local sha="$1"
  _log "watcher" "error" "Deploy timeout ${sha:0:8} after ${DEPLOY_TIMEOUT}s"
  terminal-notifier -title "❌ Deploy Timeout!" -message "Merge ${sha:0:8} not deployed after ${DEPLOY_TIMEOUT}s" -timeout 10 &
  afplay /System/Library/Sounds/Basso.aiff &
  sleep 0.4
  afplay /System/Library/Sounds/Basso.aiff
}

# ── Lock file with heartbeat ──
LOCK_FILE="/tmp/watch_deploy.lock"

write_heartbeat() {
  echo "{\"pid\": $$, \"heartbeat\": $(date +%s)}" > "$LOCK_FILE"
}

check_existing() {
  if [ ! -f "$LOCK_FILE" ]; then return; fi
  local prev_pid prev_hb age
  prev_pid=$(python3 -c "import json; print(json.load(open('$LOCK_FILE'))['pid'])" 2>/dev/null)
  prev_hb=$(python3 -c "import json; print(json.load(open('$LOCK_FILE'))['heartbeat'])" 2>/dev/null)
  if [ -z "$prev_pid" ]; then rm -f "$LOCK_FILE"; return; fi
  if [ "$prev_pid" = "$$" ]; then return; fi
  if kill -0 "$prev_pid" 2>/dev/null; then
    age=$(($(date +%s) - ${prev_hb:-0}))
    if [ "$age" -le 10 ]; then
      _log "watcher" "error" "Already running (PID $prev_pid, ${age}s ago). Exiting."
      exit 0
    fi
    _log "watcher" "info" "Stale watcher (PID $prev_pid, ${age}s). Replacing."
    kill "$prev_pid" 2>/dev/null
    sleep 0.5
  else
    _log "watcher" "info" "Dead watcher (PID $prev_pid). Cleaning up."
  fi
  rm -f "$LOCK_FILE"
}

cleanup() {
  rm -f "$LOCK_FILE"
  exit 0
}
trap cleanup INT TERM

check_existing
write_heartbeat

# Initialize state
LAST_MASTER_HEAD=$(get_master_head)
LAST_PROD_VERSION=$(get_prod_version)
WAITING_SINCE=""   # empty = idle, epoch = waiting for deploy
MERGE_SHA=""
LAST_WAITING_SHA="" # track last printed "new push while waiting" SHA

_log "watcher" "info" "Watching deploys (PID $$)"
_log "watcher" "info" "Master HEAD: ${LAST_MASTER_HEAD:0:8}"
_log "watcher" "info" "Production: $LAST_PROD_VERSION"

POLL_COUNTER=0

while true; do
  sleep 2
  POLL_COUNTER=$((POLL_COUNTER + 1))

  # Update heartbeat every ~10s
  if [ $((POLL_COUNTER % 5)) -eq 0 ]; then
    write_heartbeat
  fi

  # Poll production every 2s
  CURRENT_PROD=$(get_prod_version)

  if [ -n "$WAITING_SINCE" ]; then
    # Waiting for deploy — check if production updated
    if [ -n "$CURRENT_PROD" ] && [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
      notify_success "$CURRENT_PROD"
      LAST_PROD_VERSION="$CURRENT_PROD"
      WAITING_SINCE=""
      MERGE_SHA=""
      LAST_WAITING_SHA=""
      continue
    fi

    # Check timeout
    NOW=$(date +%s)
    ELAPSED=$((NOW - WAITING_SINCE))
    if [ "$ELAPSED" -ge "$DEPLOY_TIMEOUT" ]; then
      notify_failure "$MERGE_SHA"
      LAST_PROD_VERSION="$CURRENT_PROD"
      WAITING_SINCE=""
      MERGE_SHA=""
      LAST_WAITING_SHA=""
      continue
    fi
  else
    # Not waiting — track production version silently
    if [ -n "$CURRENT_PROD" ] && [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
      _log "watcher" "info" "Prod version: $CURRENT_PROD"
      LAST_PROD_VERSION="$CURRENT_PROD"
    fi
  fi

  # Poll GitHub every 10s
  if [ $((POLL_COUNTER % 5)) -eq 0 ]; then
    CURRENT_HEAD=$(get_master_head)
    if [ -n "$CURRENT_HEAD" ] && [ "$CURRENT_HEAD" != "$LAST_MASTER_HEAD" ]; then
      if [ -n "$WAITING_SINCE" ]; then
        # New push arrived while already waiting — print only once per unique SHA
        if [ "$CURRENT_HEAD" != "$LAST_WAITING_SHA" ]; then
          _log "watcher" "info" "New push: ${CURRENT_HEAD:0:8}"
          LAST_WAITING_SHA="$CURRENT_HEAD"
        fi
      else
        _log "watcher" "info" "Merge: ${CURRENT_HEAD:0:8} (was ${LAST_MASTER_HEAD:0:8})"
        _log "watcher" "info" "Waiting up to ${DEPLOY_TIMEOUT}s for production..."
        WAITING_SINCE=$(date +%s)
        MERGE_SHA="$CURRENT_HEAD"
      fi
      LAST_MASTER_HEAD="$CURRENT_HEAD"
    elif [ -n "$CURRENT_HEAD" ]; then
      LAST_MASTER_HEAD="$CURRENT_HEAD"
    fi
  fi
done
