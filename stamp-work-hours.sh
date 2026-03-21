#!/bin/bash
# stamp-work-hours.sh — Compute total work hours from git commit history
#
# Algorithm: group commits into sessions (30-min gap = new session),
# add 5-min buffer per session, sum all session durations.
#
# Output: static/work-hours.js with window.WORK_HOURS = <number>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_GAP=1800  # 30 minutes in seconds
SESSION_BUFFER=300  # 5 minutes buffer per session

# Get all commit timestamps sorted ascending (epoch seconds)
timestamps=$(git -C "$SCRIPT_DIR" log --format="%at" --all | sort -n)

if [ -z "$timestamps" ]; then
  echo "window.WORK_HOURS = 0;" > "$SCRIPT_DIR/static/work-hours.js"
  exit 0
fi

total_seconds=0
session_start=""
session_last=""

while read -r ts; do
  if [ -z "$session_start" ]; then
    session_start="$ts"
    session_last="$ts"
    continue
  fi

  gap=$((ts - session_last))
  if [ "$gap" -gt "$SESSION_GAP" ]; then
    # End current session
    session_duration=$((session_last - session_start + SESSION_BUFFER))
    total_seconds=$((total_seconds + session_duration))
    # Start new session
    session_start="$ts"
  fi
  session_last="$ts"
done <<< "$timestamps"

# Close final session
if [ -n "$session_start" ]; then
  session_duration=$((session_last - session_start + SESSION_BUFFER))
  total_seconds=$((total_seconds + session_duration))
fi

hours=$((total_seconds / 3600))

echo "window.WORK_HOURS = $hours;" > "$SCRIPT_DIR/static/work-hours.js"
echo "Stamped work-hours.js: ${hours}h (from $(echo "$timestamps" | wc -l | tr -d ' ') commits)"
