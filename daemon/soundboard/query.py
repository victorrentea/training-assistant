"""Query the played shorts (the tablet's Video Snippets) the room saw in a time range.

    python3 -m daemon.soundboard.query <from_iso> <to_iso> [--json]

One JSON object per moment on stdout (JSON lines); the range summary goes to stderr
so stdout stays parseable. `--json` prints a single document instead
(`{"from", "to", "moments": [...]}`), which is what the training summarizer's prewarm
saves as `soundboard.json`. Naive datetimes are local time, as in
`daemon.transcript.query`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from daemon.soundboard.plays import BURST_GAP_S, ledger_path, moments_between, play_log_path
from daemon.transcript.query import _resolve_query_range


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Video Snippets played in an ISO time interval")
    parser.add_argument("from_iso", help="Start ISO datetime: YYYY-MM-DDTHH:MM[:SS][±HH:MM]")
    parser.add_argument("to_iso", help="End ISO datetime: YYYY-MM-DDTHH:MM[:SS][±HH:MM]")
    parser.add_argument("--play-log", type=Path, default=None, help=f"default: {play_log_path()}")
    parser.add_argument("--ledger", type=Path, default=None, help=f"default: {ledger_path()}")
    parser.add_argument("--burst-gap", type=float, default=BURST_GAP_S, help="seconds (default: %(default)s)")
    parser.add_argument("--json", action="store_true", help="one JSON document instead of JSON lines")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        query = _resolve_query_range(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    moments = moments_between(
        query.start, query.end, play_log=args.play_log, ledger_file=args.ledger, burst_gap_s=args.burst_gap
    )
    if args.json:
        doc = {
            "from": query.start.isoformat(timespec="minutes"),
            "to": query.end.isoformat(timespec="minutes"),
            "moments": [m.model_dump() for m in moments],
        }
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for m in moments:
            print(m.model_dump_json())

    linked = sum(1 for m in moments if m.url)
    print(
        f"# range: {query.start.strftime('%Y-%m-%d %H:%M')} -> {query.end.strftime('%Y-%m-%d %H:%M')}"
        f" · moments: {len(moments)} · with url: {linked}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
