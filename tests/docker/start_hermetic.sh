#!/bin/bash
# Start backend + daemon + mock services + run Playwright tests in a single container.
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
export HERMETIC_TEST_MODE=1
export FIXTURE_PDF_DIR=/tmp/fixture-pdfs
export MOCK_DRIVE_PORT=9090

# Create fixture directories
mkdir -p "$SESSIONS_FOLDER" "$TRANSCRIPTION_FOLDER" "$FIXTURE_PDF_DIR" /tmp/test-pptx

# Create dummy PPTX files (just empty files — daemon only checks mtime)
touch "/tmp/test-pptx/Clean Code.pptx"
touch "/tmp/test-pptx/Design Patterns.pptx"
touch "/tmp/test-pptx/Architecture.pptx"

export PPTX_WATCH_DIR=/tmp/test-pptx

# Create version.js stub
echo "window.APP_VERSION = 'docker-hermetic';" > /app/static/version.js

# Generate fixture PDFs
python /tests/generate_fixture_pdfs.py

# Create fixture slides catalog pointing to mock Drive server
cat > /tmp/test-slides-catalog.json <<CATALOG
{
  "decks": [
    {
      "title": "Clean Code",
      "slug": "clean-code",
      "source": "/tmp/test-pptx/Clean Code.pptx",
      "target_pdf": "clean-code.pdf",
      "drive_export_url": "http://localhost:${MOCK_DRIVE_PORT}/presentation/d/clean-code/export/pdf",
      "group": "Coding"
    },
    {
      "title": "Design Patterns",
      "slug": "design-patterns",
      "source": "/tmp/test-pptx/Design Patterns.pptx",
      "target_pdf": "design-patterns.pdf",
      "drive_export_url": "http://localhost:${MOCK_DRIVE_PORT}/presentation/d/design-patterns/export/pdf",
      "group": "Coding"
    },
    {
      "title": "Architecture",
      "slug": "architecture",
      "source": "/tmp/test-pptx/Architecture.pptx",
      "target_pdf": "architecture.pdf",
      "drive_export_url": "http://localhost:${MOCK_DRIVE_PORT}/presentation/d/architecture/export/pdf",
      "group": "Design"
    }
  ]
}
CATALOG
# Overwrite the production catalog with our test catalog (backend hardcodes this path)
cp /tmp/test-slides-catalog.json /app/daemon/materials_slides_catalog.json

# Start mock Google Drive server
python /tests/mock_drive_server.py &
MOCK_DRIVE_PID=$!
sleep 0.5
echo "[startup] Mock Drive server started (PID=$MOCK_DRIVE_PID)"

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
kill $MOCK_DRIVE_PID 2>/dev/null || true
exit $TEST_EXIT
