#!/bin/bash
# Build and run the hermetic daemon test (Phase B).
# Run from repo root: bash tests/docker/build-daemon.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKER_DIR="$REPO_ROOT/tests/docker"
BUILD_DIR=$(mktemp -d)

echo "=== Preparing build context in $BUILD_DIR ==="

# Copy app code
mkdir -p "$BUILD_DIR/app/static" "$BUILD_DIR/app/railway" "$BUILD_DIR/app/daemon" "$BUILD_DIR/app/scripts"
cp -r "$REPO_ROOT/railway" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/daemon" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/static" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/scripts" "$BUILD_DIR/app/"

# Copy test page objects
mkdir -p "$BUILD_DIR/tests/pages"
cp -r "$REPO_ROOT/tests/pages/"* "$BUILD_DIR/tests/pages/"

# Copy test files
mkdir -p "$BUILD_DIR/tests/docker"
cp "$DOCKER_DIR/session_utils.py" "$BUILD_DIR/tests/docker/"
for f in "$DOCKER_DIR"/test_*.py; do
  cp "$f" "$BUILD_DIR/tests/docker/"
done
cp -r "$DOCKER_DIR/features" "$BUILD_DIR/tests/docker/"
cp -r "$DOCKER_DIR/step_defs" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/generate_fixture_pdfs.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/mock_drive_server.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/mock_github_server.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/start_hermetic.sh" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/Dockerfile.daemon" "$BUILD_DIR/"

echo "=== Building Docker image ==="
# Remove previous image to avoid dangling images piling up (~2.7 GB each)
docker rmi hermetic-daemon 2>/dev/null || true
docker build -f "$BUILD_DIR/Dockerfile.daemon" -t hermetic-daemon "$BUILD_DIR"

echo "=== Running tests ==="
# Mount generated sequences dir so test-produced .puml files persist on host
GENERATED_DIR="$REPO_ROOT/docs/sequences/extracted"
mkdir -p "$GENERATED_DIR"
# Always exclude nightly tests; additional args are appended
docker run --rm -v "$GENERATED_DIR:/app/docs/sequences/extracted" hermetic-daemon -m "not nightly" "$@"

# Cleanup
rm -rf "$BUILD_DIR"
echo "=== Done ==="
