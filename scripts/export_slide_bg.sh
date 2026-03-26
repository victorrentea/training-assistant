#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <deck-title> [materials-slides-dir]" >&2
  exit 1
fi

DECK_TITLE="$1"
DEST_DIR="${2:-/Users/victorrentea/workspace/training-assistant/materials/slides}"
CATALOG_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/daemon/materials_slides_catalog.json"

if [[ ! -f "$CATALOG_PATH" ]]; then
  echo "Catalog not found: $CATALOG_PATH" >&2
  exit 1
fi

DECK_INFO=()
while IFS= read -r line; do
  DECK_INFO+=("$line")
done < <(
  python3 - "$CATALOG_PATH" "$DECK_TITLE" <<'PY'
import json
import sys

catalog_path = sys.argv[1]
title = sys.argv[2]

with open(catalog_path, "r", encoding="utf-8") as f:
    decks = json.load(f).get("decks", [])

for deck in decks:
    if deck.get("title") == title:
        print(deck.get("source", ""))
        print(deck.get("target_pdf", ""))
        raise SystemExit(0)

raise SystemExit(2)
PY
)

if [[ ${#DECK_INFO[@]} -ne 2 ]]; then
  echo "Deck not found in catalog: $DECK_TITLE" >&2
  exit 1
fi

SOURCE_PPTX="${DECK_INFO[0]}"
TARGET_PDF_NAME="${DECK_INFO[1]}"

if [[ -z "$SOURCE_PPTX" || -z "$TARGET_PDF_NAME" ]]; then
  echo "Invalid deck entry for title: $DECK_TITLE" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_PPTX" ]]; then
  echo "Source PPTX not found: $SOURCE_PPTX" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

SOURCE_DIR="$(dirname "$SOURCE_PPTX")"
SOURCE_PDF_PATH="$SOURCE_DIR/$TARGET_PDF_NAME"
DEST_PDF_PATH="$DEST_DIR/$TARGET_PDF_NAME"

SCRIPT_FILE="$(mktemp)"
cat > "$SCRIPT_FILE" <<APPLESCRIPT
set srcPath to "$SOURCE_PPTX"
set exportPath to POSIX file "$SOURCE_PDF_PATH"

tell application "Microsoft PowerPoint"
  set targetPres to missing value
  repeat with p in presentations
    try
      if (full name of p as text) is srcPath then
        set targetPres to p
        exit repeat
      end if
    end try
  end repeat

  if targetPres is missing value then
    error "Presentation not open in PowerPoint: " & srcPath
  end if

  save targetPres in exportPath as save as PDF
end tell
APPLESCRIPT

python3 - "$SCRIPT_FILE" <<'PY'
import subprocess
import sys

script_file = sys.argv[1]
try:
    subprocess.run(["osascript", script_file], check=True, timeout=45)
except subprocess.TimeoutExpired:
    print(
        "PowerPoint export timed out after 45s (possible modal dialog or busy app state).",
        file=sys.stderr,
    )
    raise SystemExit(1)
finally:
    subprocess.run(["rm", "-f", script_file], check=False)
PY

mv -f "$SOURCE_PDF_PATH" "$DEST_PDF_PATH"
echo "Exported: $DEST_PDF_PATH"
