#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQUENCES_DIR = ROOT / "docs" / "sequences"
SVG_DIR = SEQUENCES_DIR / "svg"


def discover_puml_files(sequences_dir: Path) -> list[Path]:
    return sorted(path for path in sequences_dir.glob("*.puml") if path.is_file())


def render_puml_files(
    files: list[Path],
    output_dir: Path,
    plantuml_bin: str = "plantuml",
) -> list[Path]:
    if shutil.which(plantuml_bin) is None:
        raise SystemExit(
            f"{plantuml_bin} not found on PATH; install PlantUML or use a different plantuml_bin"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in files:
        command = [plantuml_bin, "-tsvg", "-o", str(output_dir), str(path)]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"plantuml failed for {path}"
            )
        written.append(output_dir / f"{path.stem}.svg")
    return written


def check_render_sync(
    files: list[Path],
    output_dir: Path,
    plantuml_bin: str = "plantuml",
) -> list[Path]:
    stale: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        for path in files:
            render_puml_files([path], tmp_dir, plantuml_bin=plantuml_bin)
            expected = output_dir / f"{path.stem}.svg"
            rendered = tmp_dir / f"{path.stem}.svg"
            if not expected.exists() or expected.read_bytes() != rendered.read_bytes():
                stale.append(expected)
    return stale


def build_input_snapshot(files: list[Path]) -> dict[Path, str]:
    snapshot: dict[Path, str] = {}
    for path in files:
        try:
            snapshot[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            continue
    return snapshot


def changed_puml_files(before: dict[Path, str], after: dict[Path, str]) -> list[Path]:
    return sorted(path for path, digest in after.items() if before.get(path) != digest)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render PlantUML sequence diagrams to SVG")
    parser.add_argument("paths", nargs="*")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--watch", action="store_true")
    parser.add_argument("--plantuml-bin", default="plantuml")
    return parser.parse_args(argv)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve_files(paths: list[str]) -> list[Path]:
    return [Path(path).resolve() for path in paths]


def _current_watch_files(explicit_files: list[Path]) -> list[Path]:
    return explicit_files if explicit_files else discover_puml_files(SEQUENCES_DIR)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    explicit_files = _resolve_files(args.paths)

    if args.check:
        files = explicit_files or discover_puml_files(SEQUENCES_DIR)
        if not files:
            return 0
        stale = check_render_sync(files, SVG_DIR, plantuml_bin=args.plantuml_bin)
        for path in stale:
            print(f"stale or missing: {_display_path(path)}")
        return 1 if stale else 0

    if args.watch:
        snapshot = build_input_snapshot(_current_watch_files(explicit_files))
        while True:
            time.sleep(1)
            files = _current_watch_files(explicit_files)
            current = build_input_snapshot(files)
            changed = changed_puml_files(snapshot, current)
            if changed:
                for output in render_puml_files(changed, SVG_DIR, plantuml_bin=args.plantuml_bin):
                    print(f"rendered {_display_path(output)}")
            snapshot = current
        return 0

    files = explicit_files or discover_puml_files(SEQUENCES_DIR)
    if not files:
        return 0

    for output in render_puml_files(files, SVG_DIR, plantuml_bin=args.plantuml_bin):
        print(f"rendered {_display_path(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
