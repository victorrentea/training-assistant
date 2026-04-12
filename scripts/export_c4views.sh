#!/bin/bash
# Regenerate C4 PlantUML and Mermaid exports from docs/c4model.dsl into docs/c4views/.
# Requires Docker.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DSL="docs/c4model.dsl"
OUT="docs/c4views"
IMAGE="structurizr/structurizr"

cd "$REPO_ROOT"

# Remove stale exports
rm -f "$OUT"/structurizr-*.puml "$OUT"/structurizr-*.mmd

docker run --rm -v "$REPO_ROOT":/usr/local/structurizr "$IMAGE" \
  export -workspace "$DSL" -format plantuml/c4plantuml -output "$OUT" 2>&1

docker run --rm -v "$REPO_ROOT":/usr/local/structurizr "$IMAGE" \
  export -workspace "$DSL" -format mermaid -output "$OUT" 2>&1

echo "C4 views exported to $OUT"
