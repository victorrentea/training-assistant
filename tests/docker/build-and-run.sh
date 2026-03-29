#!/bin/bash
# Build and run the hermetic session flow test.
# Run from repo root: bash tests/docker/build-and-run.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKER_DIR="$REPO_ROOT/tests/docker"
BUILD_DIR=$(mktemp -d)

echo "=== Preparing build context in $BUILD_DIR ==="

# Copy app code (only what the backend needs)
mkdir -p "$BUILD_DIR/app/static" "$BUILD_DIR/app/core" "$BUILD_DIR/app/features" "$BUILD_DIR/app/daemon"
cp "$REPO_ROOT/main.py" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/core" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/features" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/daemon" "$BUILD_DIR/app/"
cp -r "$REPO_ROOT/static" "$BUILD_DIR/app/"

# Copy test files
mkdir -p "$BUILD_DIR/tests/docker"
cp "$DOCKER_DIR/mock_daemon.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/test_session_flow.py" "$BUILD_DIR/tests/docker/"
cp "$DOCKER_DIR/Dockerfile.session" "$BUILD_DIR/"

echo "=== Building Docker image ==="
docker build -f "$BUILD_DIR/Dockerfile.session" -t hermetic-session "$BUILD_DIR"

echo "=== Running tests ==="
docker run --rm hermetic-session

# Cleanup
rm -rf "$BUILD_DIR"
echo "=== Done ==="
