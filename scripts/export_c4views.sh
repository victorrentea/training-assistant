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
rm -f "$OUT"/*.puml "$OUT"/*.mmd

docker run --rm -v "$REPO_ROOT":/usr/local/structurizr "$IMAGE" \
  export -workspace "$DSL" -format plantuml/c4plantuml -output "$OUT" 2>&1

docker run --rm -v "$REPO_ROOT":/usr/local/structurizr "$IMAGE" \
  export -workspace "$DSL" -format mermaid -output "$OUT" 2>&1

# Strip "structurizr-" prefix and convert PascalCase to kebab-case
# e.g. structurizr-C3DaemonOnly.puml -> C3-Daemon-Only.puml
for f in "$OUT"/structurizr-*; do
  [ -f "$f" ] || continue
  newname=$(basename "$f" \
    | sed 's/^structurizr-//' \
    | sed 's/\([a-z0-9]\)\([A-Z]\)/\1-\2/g' \
    | sed 's/\([A-Z]\)\([A-Z][a-z]\)/\1-\2/g')
  mv "$f" "$OUT/$newname"
done

echo "C4 views exported to $OUT"
