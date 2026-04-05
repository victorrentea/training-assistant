#!/bin/bash
# Build and run the hermetic daemon test (Phase B).
# Run from repo root: bash tests/docker/build-daemon.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKER_DIR="$REPO_ROOT/tests/docker"
BUILD_DIR=$(mktemp -d)

echo "=== Preparing build context in $BUILD_DIR ==="

# Copy app code
mkdir -p "$BUILD_DIR/app/static" "$BUILD_DIR/app/core" "$BUILD_DIR/app/features" "$BUILD_DIR/app/daemon"
cp "$REPO_ROOT/main.py" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/core" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/features" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/daemon" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/static" "$BUILD_DIR/app/"

# Copy test page objects
mkdir -p "$BUILD_DIR/tests/pages"
cp -r "$REPO_ROOT/tests/pages/"* "$BUILD_DIR/tests/pages/"

# Copy test files
mkdir -p "$BUILD_DIR/tests/docker"
cp "$DOCKER_DIR/session_utils.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_daemon_connected.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_poll_flow.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_slides_view.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_follow_me.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_participant_interactions.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_qa_wordcloud.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_integrations.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_high_value.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_poll_advanced.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_ui_interactions.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_slides_advanced.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_regressions.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_unique_avatars.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_follow_mode_slow_drive.py" "$BUILD_DIR/tests/docker/"
cp -r "$DOCKER_DIR/features" "$BUILD_DIR/tests/docker/"
cp -r "$DOCKER_DIR/step_defs" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/generate_fixture_pdfs.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/mock_drive_server.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/start_hermetic.sh" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/Dockerfile.daemon" "$BUILD_DIR/"

echo "=== Building Docker image ==="
# Remove previous image to avoid dangling images piling up (~2.7 GB each)
docker rmi hermetic-daemon 2>/dev/null || true
docker build -f "$BUILD_DIR/Dockerfile.daemon" -t hermetic-daemon "$BUILD_DIR"

echo "=== Running tests ==="
# Always exclude nightly tests; additional args are appended
docker run --rm hermetic-daemon -m "not nightly" "$@"

# Cleanup
rm -rf "$BUILD_DIR"
echo "=== Done ==="
