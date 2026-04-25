#!/usr/bin/env bash
# Remove the nightly hermetic schedule.
set -uo pipefail

PLIST_LABEL="com.victor.hermetic-nightly"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null && \
    echo "launchd agent unloaded" || echo "launchd agent was not loaded"
rm -f "$PLIST_PATH" && echo "Removed $PLIST_PATH"

echo
echo "Cancelling pmset wake schedule (sudo required)..."
sudo pmset repeat cancel
pmset -g sched | sed 's/^/  /'
