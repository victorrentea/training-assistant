#!/usr/bin/env bash
# One-time install of Quartz (https://quartz.jzhao.xyz), the open-source Obsidian
# publisher the daemon uses to turn a session's wiki/ folder into the static site
# participants browse under the "Wiki" menu entry.
#
# Re-run it to upgrade Quartz. The daemon copies daemon/wiki/quartz/* in and
# re-applies the graph patch on every build, so config changes need no re-run.
set -euo pipefail

QUARTZ_DIR="${QUARTZ_DIR:-$HOME/.cache/training-assistant/quartz}"

if [ -d "$QUARTZ_DIR/.git" ]; then
  git -C "$QUARTZ_DIR" checkout -- .
  git -C "$QUARTZ_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$QUARTZ_DIR")"
  git clone --depth 1 --branch v4 https://github.com/jackyzha0/quartz.git "$QUARTZ_DIR"
fi
rm -f "$QUARTZ_DIR/quartz/components/scripts/graph.inline.ts.orig"

cd "$QUARTZ_DIR"
npm ci --no-audit --no-fund
echo "Quartz ready in $QUARTZ_DIR"
