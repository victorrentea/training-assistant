#!/bin/bash
# Wait until the live site serves the version stamped in static/version.js, then ring a bell.
# Usage: ./wait-for-deploy.sh   (run after git push)

EXPECTED=$(grep -o "'.*'" static/version.js | tr -d "'")
URL="https://interact.victorrentea.ro/static/version.js"

echo "Waiting for deploy: $EXPECTED"

for i in $(seq 1 40); do
  LIVE=$(curl -s "$URL" | grep -o "'.*'" | tr -d "'")
  if [ "$LIVE" = "$EXPECTED" ]; then
    echo "Deployed! ($LIVE)"
    # YouTube-style notification ding (two quick tones)
    afplay /System/Library/Sounds/Glass.aiff &
    sleep 0.4
    afplay /System/Library/Sounds/Glass.aiff
    exit 0
  fi
  echo "  [$i] live=$LIVE — retrying in 5s…"
  sleep 5
done

echo "Timed out waiting for deploy."
exit 1
