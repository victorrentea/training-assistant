#!/bin/bash
# Install wispr-addons as a macOS login item (LaunchAgent)
set -e

PLIST_NAME="ro.victorrentea.wispr-addons.plist"
PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

ln -sf "$PLIST_SRC" "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ wispr-addons installed as login item"
echo "   Logs: tail -f /tmp/wispr-addons.log"
