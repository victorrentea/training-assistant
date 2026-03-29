#!/usr/bin/env python3
"""Generate static/deploy-info.json from local git history."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_INFO_PATH = PROJECT_ROOT / "static" / "deploy-info.json"


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def maybe_run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def parse_prev_sha() -> str:
    if not DEPLOY_INFO_PATH.exists():
        return ""
    try:
        data = json.loads(DEPLOY_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = data.get("sha", "")
    return value if isinstance(value, str) else ""


def compute_changelog(prev_sha: str) -> list[str]:
    if prev_sha and maybe_run_git("cat-file", "-e", prev_sha):
        raw = run_git(
            "log",
            f"{prev_sha}..HEAD",
            "--no-merges",
            "--author-date-order",
            "--invert-grep",
            "--grep=chore: update deploy-info",
            "--format=%s",
            "-20",
        )
        lines = [line for line in raw.splitlines() if line.strip()]
        if lines:
            return lines
    latest = run_git("log", "-1", "--format=%s", "HEAD")
    return [latest] if latest else []


def compute_commits() -> list[dict[str, str]]:
    raw = run_git(
        "log",
        "-20",
        "--no-merges",
        "--invert-grep",
        "--grep=chore: update deploy-info",
        "--format=%H|%s|%aI",
    )
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        sha, msg, ts = (line.split("|", 2) + ["", ""])[:3]
        if not sha or not ts:
            continue
        commits.append({"sha": sha[:8], "msg": msg, "ts": ts})
    return commits


def compute_branches() -> list[dict[str, int | str]]:
    raw = maybe_run_git(
        "for-each-ref",
        "--format=%(objectname:short) %(authordate:format:%Y-%m-%dT%H:%M:%S%z) %(refname:short)",
        "--sort=-authordate",
        "refs/remotes/origin/victorrentea/",
    )
    entries: list[tuple[datetime, str, str]] = []
    for line in raw.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        sha, date_str, refname = parts
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            continue
        branch = refname.replace("origin/victorrentea/", "", 1)
        entries.append((dt, sha, branch))

    result: list[dict[str, int | str]] = []
    for i, (dt, sha, branch) in enumerate(entries[:30]):
        gap_seconds = 0.0
        if i + 1 < len(entries):
            gap_seconds = (dt - entries[i + 1][0]).total_seconds()
        result.append(
            {
                "branch": branch,
                "sha": sha,
                "minutes": max(0, int(gap_seconds / 60)),
            }
        )

    result.sort(key=lambda item: int(item["minutes"]), reverse=True)
    return result[:20]


def build_payload(now: datetime) -> dict[str, object]:
    prev_sha = parse_prev_sha()
    return {
        "sha": run_git("rev-parse", "HEAD"),
        "timestamp": now.strftime("%Y-%m-%d %H:%M"),
        "changelog": compute_changelog(prev_sha),
        "commits": compute_commits(),
        "branches": compute_branches(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when static/deploy-info.json is outdated",
    )
    args = parser.parse_args()

    now = datetime.now(ZoneInfo("Europe/Bucharest"))
    payload = build_payload(now)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    current = ""
    if DEPLOY_INFO_PATH.exists():
        current = DEPLOY_INFO_PATH.read_text(encoding="utf-8")

    if args.check:
        if current != rendered:
            print("static/deploy-info.json is outdated. Run scripts/generate_deploy_info.py")
            return 1
        print("static/deploy-info.json is up to date")
        return 0

    DEPLOY_INFO_PATH.write_text(rendered, encoding="utf-8")
    print(f"Updated {DEPLOY_INFO_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
