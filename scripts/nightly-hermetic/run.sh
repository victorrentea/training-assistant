#!/usr/bin/env bash
# Nightly hermetic test runner. Invoked by launchd at ~02:05 after pmset wakes the Mac.
# Pulls latest master, ensures Docker is up, runs hermetic tests, emails on failure.
set -uo pipefail

REPO="/Users/victorrentea/workspace/training-assistant"
LOG_DIR="$HOME/Library/Logs/training-assistant-hermetic"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT_SECONDS=1800  # 30 minutes hard cap on test run

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y-%m-%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

# Make brew/python/gh visible to launchd's restricted PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

fail() {
    local reason="$1"
    echo "[$(ts)] FAIL: $reason"
    if [ -f "$HOME/.training-assistants-secrets.env" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.training-assistants-secrets.env"
    fi
    if [ -n "${AGENTMAIL_API_KEY:-}" ]; then
        python3 "$SCRIPT_DIR/send_failure_email.py" "$reason" "$LOG" || \
            echo "[$(ts)] email send failed (non-fatal)"
    else
        echo "[$(ts)] AGENTMAIL_API_KEY not set; skipping email"
    fi
    exit 1
}

echo "[$(ts)] === Nightly hermetic run starting ==="
echo "[$(ts)] Log: $LOG"

# 1. Start Docker if not running
if ! docker info >/dev/null 2>&1; then
    echo "[$(ts)] Docker not running; launching Docker.app"
    open -a Docker
    for i in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            echo "[$(ts)] Docker ready after ${i}x2s"
            break
        fi
        sleep 2
    done
    docker info >/dev/null 2>&1 || fail "Docker did not start within 2 minutes"
fi

# 2. Sync to latest master
cd "$REPO" || fail "repo not found at $REPO"
echo "[$(ts)] Fetching origin/master"
git fetch --quiet origin master || fail "git fetch failed"
git checkout --quiet master || fail "git checkout master failed"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(ts)] Resetting working tree to origin/master ($REMOTE)"
    git reset --hard --quiet origin/master || fail "git reset failed"
fi
echo "[$(ts)] HEAD = $(git log -1 --oneline)"

# 3. Run hermetic tests with hard timeout
echo "[$(ts)] Running hermetic tests (timeout ${TIMEOUT_SECONDS}s)"
TEST_LOG="$LOG_DIR/$(basename "$LOG" .log)-tests.log"
if /usr/bin/env timeout "${TIMEOUT_SECONDS}s" bash tests/docker/run-hermetic.sh -m nightly 2>&1 | tee "$TEST_LOG"; then
    echo "[$(ts)] === Nightly hermetic run SUCCEEDED ==="
    exit 0
else
    EXIT=${PIPESTATUS[0]}
    if [ "$EXIT" -eq 124 ]; then
        fail "tests timed out after ${TIMEOUT_SECONDS}s"
    else
        fail "tests exited with code $EXIT"
    fi
fi
