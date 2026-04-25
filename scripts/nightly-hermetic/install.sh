#!/usr/bin/env bash
# Install nightly hermetic test schedule on this Mac.
# Two layers:
#   1. pmset repeat — wakes the Mac at 02:00 every night (needs sudo).
#   2. launchd LaunchAgent — runs run.sh at 02:05 (no sudo needed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_LABEL="com.victor.hermetic-nightly"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
RUN_SCRIPT="$SCRIPT_DIR/run.sh"
WAKE_HOUR=2
WAKE_MIN=0
JOB_HOUR=2
JOB_MIN=5

chmod +x "$RUN_SCRIPT" "$SCRIPT_DIR/send_failure_email.py"

# 1. Generate plist (overwrites any prior install with current paths)
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs/training-assistant-hermetic"
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>${RUN_SCRIPT}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>${JOB_HOUR}</integer>
        <key>Minute</key><integer>${JOB_MIN}</integer>
    </dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>${HOME}/Library/Logs/training-assistant-hermetic/launchd.out.log</string>
    <key>StandardErrorPath</key><string>${HOME}/Library/Logs/training-assistant-hermetic/launchd.err.log</string>
</dict>
</plist>
PLIST
echo "Wrote $PLIST_PATH"

# 2. Reload the agent
launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${PLIST_LABEL}"
echo "launchd agent loaded: ${PLIST_LABEL}"

# 3. pmset wake schedule (requires sudo). Schedule is replaced atomically.
echo
echo "Setting pmset wake schedule (sudo required)..."
WAKE_TIME=$(printf "%02d:%02d:00" "$WAKE_HOUR" "$WAKE_MIN")
sudo pmset repeat wakeorpoweron MTWRFSU "$WAKE_TIME"

echo
echo "=== Install complete ==="
echo "Wake schedule:"
pmset -g sched | sed 's/^/  /'
echo
echo "launchd job:"
launchctl print "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null \
    | grep -E "^\s+(state|run interval|next run|program|stdout|stderr)" \
    | sed 's/^/  /' || launchctl list | grep "$PLIST_LABEL" || true
echo
echo "Logs will appear under: \$HOME/Library/Logs/training-assistant-hermetic/"
echo "To uninstall: bash $SCRIPT_DIR/uninstall.sh"
echo
echo "REMINDER: add AGENTMAIL_API_KEY to ~/.training-assistants-secrets.env"
echo "  (the run script sources that file before sending failure emails)"
