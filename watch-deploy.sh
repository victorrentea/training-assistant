#!/bin/bash
# Continuous deploy watcher — detects merges to master and verifies production deploys.
# Polls production every 2s, GitHub master HEAD every 10s.
# When master HEAD changes, waits up to 2 minutes for production to reflect the new version.
# Usage: ./watch-deploy.sh   (run once, runs indefinitely)

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
