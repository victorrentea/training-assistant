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

get_prod_version() {
  curl -s "$PROD_URL" | grep -o "'.*'" | tr -d "'"
}

get_master_head() {
  gh api "repos/$REPO/commits/master" --jq '.sha' 2>/dev/null
}

notify_success() {
  local version="$1"
  echo "$(date '+%H:%M:%S') ✅ Deployed! Version: $version"
  terminal-notifier -title "🚀 Deployed!" -message "Version $version is live" -timeout 5 &
  afplay /System/Library/Sounds/Glass.aiff &
  sleep 0.4
  afplay /System/Library/Sounds/Glass.aiff
}

notify_failure() {
  local sha="$1"
  echo "$(date '+%H:%M:%S') ❌ Deploy timeout! Master moved to ${sha:0:8} but production didn't update within ${DEPLOY_TIMEOUT}s"
  terminal-notifier -title "❌ Deploy Timeout!" -message "Merge ${sha:0:8} not deployed after ${DEPLOY_TIMEOUT}s" -timeout 10 &
  afplay /System/Library/Sounds/Basso.aiff &
  sleep 0.4
  afplay /System/Library/Sounds/Basso.aiff
}

# Initialize state
LAST_MASTER_HEAD=$(get_master_head)
LAST_PROD_VERSION=$(get_prod_version)
WAITING_SINCE=""  # empty = idle, timestamp = waiting for deploy
MERGE_SHA=""

echo "$(date '+%H:%M:%S') 👀 Watching deploys..."
echo "  Master HEAD: ${LAST_MASTER_HEAD:0:8}"
echo "  Production:  $LAST_PROD_VERSION"

POLL_COUNTER=0

while true; do
  sleep 2
  POLL_COUNTER=$((POLL_COUNTER + 1))

  # Poll production every 2s
  CURRENT_PROD=$(get_prod_version)

  if [ -n "$WAITING_SINCE" ]; then
    # We're waiting for a deploy — check if production updated
    if [ "$CURRENT_PROD" != "$LAST_PROD_VERSION" ]; then
      notify_success "$CURRENT_PROD"
      LAST_PROD_VERSION="$CURRENT_PROD"
      WAITING_SINCE=""
      MERGE_SHA=""
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
      continue
    fi
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
      echo "$(date '+%H:%M:%S') 🔀 Merge detected! Master HEAD: ${CURRENT_HEAD:0:8} (was ${LAST_MASTER_HEAD:0:8})"
      echo "  Waiting up to ${DEPLOY_TIMEOUT}s for production to update..."
      LAST_MASTER_HEAD="$CURRENT_HEAD"
      WAITING_SINCE=$(date +%s)
      MERGE_SHA="$CURRENT_HEAD"
    elif [ -n "$CURRENT_HEAD" ]; then
      LAST_MASTER_HEAD="$CURRENT_HEAD"
    fi
  fi
done
