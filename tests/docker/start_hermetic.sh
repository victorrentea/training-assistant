#!/bin/bash
# Start backend + daemon + run Playwright tests in a single container.
set -e

export HOST_USERNAME=host
export HOST_PASSWORD=testpass
export ANTHROPIC_API_KEY=sk-test-dummy-key-for-hermetic-testing
export SESSIONS_FOLDER=/tmp/test-sessions
export TRANSCRIPTION_FOLDER=/tmp/test-transcriptions
export WORKSHOP_SERVER_URL=http://localhost:8000
export DAEMON_ADAPTER=stub
export LLM_ADAPTER=stub
export MATERIALS_MIRROR_ENABLED=0
export TRANSCRIPT_LLM_CLEAN=0
export PYTHONUNBUFFERED=1

# Create fixture directories
mkdir -p "$SESSIONS_FOLDER" "$TRANSCRIPTION_FOLDER"

# Create version.js stub
echo "window.APP_VERSION = 'docker-hermetic';" > /app/static/version.js

# Start FastAPI backend
cd /app
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/api/status >/dev/null 2>&1; then
        echo "[startup] Backend ready after ${i}s"
        break
    fi
    sleep 0.5
done

# Start real daemon
python -m daemon &
DAEMON_PID=$!

# Give daemon time to connect WS
sleep 2
echo "[startup] Daemon started (PID=$DAEMON_PID)"

# Run tests
cd /tests
pytest "$@"
TEST_EXIT=$?

# Cleanup
kill $DAEMON_PID 2>/dev/null || true
kill $BACKEND_PID 2>/dev/null || true
exit $TEST_EXIT
