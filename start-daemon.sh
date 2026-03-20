#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# start-daemon.sh — Start the local quiz daemon
# ═══════════════════════════════════════════════════════════════════
#
# Starts quiz_daemon.py which:
#   - Polls the workshop server for quiz generation requests
#   - Generates questions via Claude API from transcripts or topics
#   - Indexes local materials (PDFs, EPUBs) for RAG-grounded questions
#   - Appends heartbeat timestamps to the active transcript
#   - Auto-detects today's session folder for notes
#
# The daemon self-deduplicates via /tmp/quiz_daemon.lock (PID + heartbeat).
# If a previous instance is healthy (PID alive + recent heartbeat), it exits.
# If the previous instance crashed (PID dead), it cleans up and starts.
# If the PID is alive but heartbeat is stale, it kills and replaces it.
#
# PREREQUISITES
#   - Python 3.12+
#   - pip install -e . && pip install -e daemon/
#   - secrets.env with ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER
#
# USAGE
#   ./start-daemon.sh        # foreground (see logs live)
#   ./start-daemon.sh &      # background
#
# ═══════════════════════════════════════════════════════════════════

cd "$(dirname "$0")"

if [ ! -f secrets.env ]; then
  echo "❌ secrets.env not found. Create it with at least ANTHROPIC_API_KEY and TRANSCRIPTION_FOLDER."
  exit 1
fi

while true; do
  echo "🚀 Starting quiz daemon..."
  python3 quiz_daemon.py
  exit_code=$?

  if [ $exit_code -eq 42 ]; then
    echo ""
    echo "🔄 Server version changed — pulling latest code..."
    if ! git pull; then
      echo "❌ git pull failed. Please resolve manually."
      exit 1
    fi
    echo "✅ Code updated. Restarting daemon..."
    echo ""
    continue
  elif [ $exit_code -eq 0 ]; then
    echo "👋 Daemon stopped normally."
    exit 0
  else
    echo "❌ Daemon exited with error code $exit_code."
    exit $exit_code
  fi
done
