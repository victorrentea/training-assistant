#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# watch-deploy.sh — Continuous deploy watcher
# ═══════════════════════════════════════════════════════════════════
#
# DESIGN GOALS
#
#   1. Detect new production deploys fast.
#      Production version is polled every 2s — a cheap GET to a
#      static file. Deploy detection latency is at most 2 seconds.
#
#   2. Detect merges to master with acceptable delay.
#      GitHub master HEAD is polled every 10s (well within the
#      5000 req/hour API rate limit at ~360 req/hour). This adds
#      at most 10s of detection lag — acceptable because the real
#      bottleneck is Railway's ~40-50s build time, and the deploy
#      timeout is 2 minutes.
#
#   3. Alert on deploy failures, not just successes.
#      When a merge is detected, a 2-minute countdown starts.
#      If production doesn't reflect a new version within that
#      window, a failure notification fires. This catches Railway
#      build errors, configuration issues, or stuck deploys.
#
#   4. Run-and-forget: start once per work session, runs forever.
#      Merges happen from the GitHub web UI, not from the CLI,
#      so the watcher cannot be triggered by a git hook. Instead
#      it runs as a background process, watching autonomously.
#
# USAGE
#   ./watch-deploy.sh        # foreground
#   ./watch-deploy.sh &      # background (typical)
#
# ═══════════════════════════════════════════════════════════════════

REPO="victorrentea/training-assistant"
PROD_URL="https://interact.victorrentea.ro/static/version.js"
DEPLOY_TIMEOUT=120  # seconds to wait for production after a merge

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HISTORY_FILE="$SCRIPT_DIR/deploy-history.txt"
DEFAULT_ESTIMATE=45
ESTIMATED=""
COMMIT_MSG=""

get_prod_version() {
  curl -s "$PROD_URL" | grep -o "'.*'" | tr -d "'"
}

get_master_head() {
  gh api "repos/$REPO/commits/master" --jq '.sha' 2>/dev/null
}

get_commit_message() {
  local sha="$1"
  gh api "repos/$REPO/commits/$sha" --jq '.commit.message' 2>/dev/null | head -1
}

get_estimated_duration() {
  if [ ! -f "$HISTORY_FILE" ] || [ ! -s "$HISTORY_FILE" ]; then
    echo "$DEFAULT_ESTIMATE"
    return
  fi
  local sum=0 count=0 dur
  while read -r _ts dur; do
    if [ -n "$dur" ]; then
      sum=$((sum + dur))
      count=$((count + 1))
    fi
  done < "$HISTORY_FILE"
  if [ "$count" -eq 0 ]; then
    echo "$DEFAULT_ESTIMATE"
  else
    echo $((sum / count))
  fi
}

record_deploy() {
  local duration="$1"
  echo "$(date +%s) $duration" >> "$HISTORY_FILE"
  # Trim to last 20 entries
  local line_count
  line_count=$(wc -l < "$HISTORY_FILE" | tr -d ' ')
  if [ "$line_count" -gt 20 ]; then
    tail -n 20 "$HISTORY_FILE" > "$HISTORY_FILE.tmp" && mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"
  fi
}

NOTIFY_INTERVAL=5  # minimum seconds between countdown notifications
LAST_NOTIFY_TIME=0

notify_countdown() {
  local remaining="$1"
  local now
  now=$(date +%s)
  # Throttle: skip if less than NOTIFY_INTERVAL since last notification
  if [ $((now - LAST_NOTIFY_TIME)) -lt "$NOTIFY_INTERVAL" ]; then
    return
  fi
  LAST_NOTIFY_TIME="$now"
  local title="🚀 Deploying"
  if [ -n "$COMMIT_MSG" ]; then
    title="🚀 Deploying: $COMMIT_MSG"
  fi
  local msg
  if [ "$remaining" -le 0 ]; then
    msg="Should be live... still checking"
  elif [ "$remaining" -le 5 ]; then
    msg="Any moment now..."
  else
    msg="~${remaining}s remaining"
  fi
  terminal-notifier -title "$title" -message "$msg" -group deploy &>/dev/null &
}

notify_success() {
  local version="$1"
  echo "$(date '+%H:%M:%S') ✅ Deployed! Version: $version"
  terminal-notifier -title "🚀 Deployed!" -message "Version $version is live" -group deploy -timeout 5 &
  afplay /System/Library/Sounds/Glass.aiff &
  sleep 0.4
  afplay /System/Library/Sounds/Glass.aiff
}

notify_failure() {
  local sha="$1"
  echo "$(date '+%H:%M:%S') ❌ Deploy timeout! Master moved to ${sha:0:8} but production didn't update within ${DEPLOY_TIMEOUT}s"
  terminal-notifier -title "❌ Deploy Timeout!" -message "Merge ${sha:0:8} not deployed after ${DEPLOY_TIMEOUT}s" -group deploy -timeout 10 &
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
  local prev_pid prev_hb now age
  prev_pid=$(python3 -c "import json,sys; print(json.load(open('$LOCK_FILE'))['pid'])" 2>/dev/null)
  prev_hb=$(python3 -c "import json,sys; print(json.load(open('$LOCK_FILE'))['heartbeat'])" 2>/dev/null)
  if [ -z "$prev_pid" ]; then rm -f "$LOCK_FILE"; return; fi
  if [ "$prev_pid" = "$$" ]; then return; fi
  if kill -0 "$prev_pid" 2>/dev/null; then
    now=$(date +%s)
    age=$((now - prev_hb))
    if [ "$age" -le 10 ]; then
      echo "$(date '+%H:%M:%S') 👀 Deploy watcher already running (PID $prev_pid, heartbeat ${age}s ago). Exiting."
      exit 0
    else
      echo "$(date '+%H:%M:%S') ⚠️  Previous watcher (PID $prev_pid) alive but stale (${age}s). Killing it."
      kill "$prev_pid" 2>/dev/null
      sleep 0.5
    fi
  else
    echo "$(date '+%H:%M:%S') 🧹 Previous watcher (PID $prev_pid) is dead. Cleaning up."
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
WAITING_SINCE=""  # empty = idle, timestamp = waiting for deploy
MERGE_SHA=""

echo "$(date '+%H:%M:%S') 👀 Watching deploys... (PID $$)"
echo "  Master HEAD: ${LAST_MASTER_HEAD:0:8}"
echo "  Production:  $LAST_PROD_VERSION"

POLL_COUNTER=0

while true; do
  sleep 2
  POLL_COUNTER=$((POLL_COUNTER + 1))

  # Update heartbeat every ~10s (every 5th iteration)
  if [ $((POLL_COUNTER % 5)) -eq 0 ]; then
    write_heartbeat
  fi

  # Poll production every 2s
  CURRENT_PROD=$(get_prod_version)

  if [ -n "$WAITING_SINCE" ]; then
    NOW=$(date +%s)
    ELAPSED=$((NOW - WAITING_SINCE))

    # We're waiting for a deploy — check if production updated
    if [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
      if [ "$MERGE_SHA" = "$LAST_MASTER_HEAD" ]; then
        # This deploy matches the push we're tracking — real success
        record_deploy "$ELAPSED"
        notify_success "$CURRENT_PROD"
        LAST_PROD_VERSION="$CURRENT_PROD"
        WAITING_SINCE=""
        MERGE_SHA=""
        ESTIMATED=""
        COMMIT_MSG=""
        continue
      else
        # Stale deploy from an older push — keep waiting for the newer one
        echo "$(date '+%H:%M:%S') 🔄 Stale deploy landed ($CURRENT_PROD), still waiting for ${MERGE_SHA:0:8}"
        LAST_PROD_VERSION="$CURRENT_PROD"
      fi
    fi

    # Check timeout
    if [ "$ELAPSED" -ge "$DEPLOY_TIMEOUT" ]; then
      notify_failure "$MERGE_SHA"
      LAST_PROD_VERSION="$CURRENT_PROD"
      WAITING_SINCE=""
      MERGE_SHA=""
      ESTIMATED=""
      COMMIT_MSG=""
      continue
    fi

    # Send countdown notification (throttled to every 5s)
    REMAINING=$((ESTIMATED - ELAPSED))
    notify_countdown "$REMAINING"
  else
    # Not waiting — track production version silently
    if [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
      echo "$(date '+%H:%M:%S') 🔄 Production version changed: $CURRENT_PROD"
      LAST_PROD_VERSION="$CURRENT_PROD"
    fi
  fi

  # Poll GitHub every 10s (every 5th iteration of the 2s loop)
  if [ $((POLL_COUNTER % 5)) -eq 0 ]; then
    CURRENT_HEAD=$(get_master_head)
    if [ -n "$CURRENT_HEAD" ] && [ "$CURRENT_HEAD" != "$LAST_MASTER_HEAD" ]; then
      ESTIMATED=$(get_estimated_duration)
      COMMIT_MSG=$(get_commit_message "$CURRENT_HEAD")
      echo "$(date '+%H:%M:%S') 🔀 Merge detected! Master HEAD: ${CURRENT_HEAD:0:8} (was ${LAST_MASTER_HEAD:0:8})"
      echo "  Commit: $COMMIT_MSG"
      echo "  Waiting up to ${DEPLOY_TIMEOUT}s for production to update..."
      LAST_MASTER_HEAD="$CURRENT_HEAD"
      WAITING_SINCE=$(date +%s)
      MERGE_SHA="$CURRENT_HEAD"
      # Send initial countdown notification (resets throttle)
      LAST_NOTIFY_TIME=0
      notify_countdown "$ESTIMATED"
    elif [ -n "$CURRENT_HEAD" ]; then
      LAST_MASTER_HEAD="$CURRENT_HEAD"
    fi
  fi
done
