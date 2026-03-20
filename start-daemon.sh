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
# The daemon self-deduplicates: if a previous instance is running,
# it kills it automatically (via /tmp/quiz_daemon.pid).
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

echo "🚀 Starting quiz daemon..."
python3 quiz_daemon.py
