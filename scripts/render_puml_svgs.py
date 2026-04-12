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
_SEQUENCES_BASE = ROOT / "docs" / "sequences"
PUML_DIRS: list[Path] = [
    _SEQUENCES_BASE / "manual",
    _SEQUENCES_BASE / "extracted",
]


def _svg_dir_for(puml_dir: Path) -> Path:
    return puml_dir / "svg"


def discover_puml_files(puml_dirs: list[Path] | None = None) -> list[Path]:
    dirs = puml_dirs if puml_dirs is not None else PUML_DIRS
    files: list[Path] = []
    for d in dirs:
        files.extend(path for path in d.glob("*.puml") if path.is_file())
    return sorted(files)


def render_puml_files(
    files: list[Path],
    output_dir: Path | None = None,
    plantuml_bin: str = "plantuml",
) -> list[Path]:
    """Render a list of .puml files to SVG.

    If *output_dir* is None each file is rendered into the ``svg/`` subfolder
    that lives next to its source directory (i.e. ``file.parent / "svg"``).
    When *output_dir* is given all outputs land in that single directory
    (legacy behaviour used by check_render_sync's tmp-dir pass).
    """
    if shutil.which(plantuml_bin) is None:
        raise SystemExit(
            f"{plantuml_bin} not found on PATH; install PlantUML or use a different plantuml_bin"
        )

    written: list[Path] = []
    for path in files:
        dest = output_dir if output_dir is not None else _svg_dir_for(path.parent)
        dest.mkdir(parents=True, exist_ok=True)
        command = [plantuml_bin, "-tsvg", "-o", str(dest), str(path)]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"plantuml failed for {path}"
            )
        written.append(dest / f"{path.stem}.svg")
    return written


def check_render_sync(
    files: list[Path],
    plantuml_bin: str = "plantuml",
) -> list[Path]:
    """Return SVG paths that are missing or out-of-date.

    Each file's expected SVG lives in ``_svg_dir_for(file.parent)``.
    """
    stale: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        for path in files:
            render_puml_files([path], output_dir=tmp_dir, plantuml_bin=plantuml_bin)
            expected = _svg_dir_for(path.parent) / f"{path.stem}.svg"
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
    parser.add_argument("--delete-orphans", action="store_true")
    parser.add_argument("--plantuml-bin", default="plantuml")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args(argv)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve_files(paths: list[str]) -> list[Path]:
    return [Path(path).resolve() for path in paths]


def _current_watch_files(explicit_files: list[Path]) -> list[Path]:
    return explicit_files if explicit_files else discover_puml_files()


def _sync_source_files(explicit_files: list[Path]) -> list[Path]:
    source_files = {path.resolve(): path.resolve() for path in discover_puml_files()}
    for path in explicit_files:
        if path.exists():
            source_files[path] = path
    return sorted(source_files.values())


def _find_orphaned_svgs(source_files: list[Path]) -> list[Path]:
    """Find SVGs in all known svg/ subdirs that have no matching source .puml."""
    orphans: list[Path] = []
    for puml_dir in PUML_DIRS:
        svg_dir = _svg_dir_for(puml_dir)
        if not svg_dir.exists():
            continue
        # stems that belong to this puml_dir
        source_stems = {path.stem for path in source_files if path.parent == puml_dir}
        orphans.extend(
            path
            for path in svg_dir.glob("*.svg")
            if path.is_file() and path.stem not in source_stems
        )
    return sorted(orphans)


def _delete_outputs(outputs: list[Path]) -> list[Path]:
    deleted_outputs: list[Path] = []
    for output in outputs:
        if output.exists():
            output.unlink()
            deleted_outputs.append(output)
    return deleted_outputs


def _render_with_orphan_cleanup(
    files_to_render: list[Path],
    source_files: list[Path],
    plantuml_bin: str = "plantuml",
) -> tuple[list[Path], list[Path]]:
    rendered_outputs = (
        render_puml_files(files_to_render, plantuml_bin=plantuml_bin)
        if files_to_render
        else []
    )
    deleted_outputs = _delete_outputs(_find_orphaned_svgs(source_files))
    return rendered_outputs, deleted_outputs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    explicit_files = _resolve_files(args.paths)

    if args.check:
        source_files = _sync_source_files(explicit_files)
        files = explicit_files or discover_puml_files()
        stale = check_render_sync(files, plantuml_bin=args.plantuml_bin)
        orphaned = _find_orphaned_svgs(source_files)
        for path in stale:
            print(f"stale or missing: {_display_path(path)}")
        for path in orphaned:
            print(f"orphaned: {_display_path(path)}")
        return 1 if stale or orphaned else 0

    if args.watch:
        snapshot = build_input_snapshot(_current_watch_files(explicit_files))
        first_cycle = True
        while True:
            if first_cycle:
                first_cycle = False
            else:
                time.sleep(1)
            watch_files = _current_watch_files(explicit_files)
            current = build_input_snapshot(watch_files)
            live_source_files = sorted(current.keys())
            changed = changed_puml_files(snapshot, current)
            orphaned_outputs = _find_orphaned_svgs(live_source_files)
            if changed:
                for output in render_puml_files(changed, plantuml_bin=args.plantuml_bin):
                    print(f"rendered {_display_path(output)}")
            for output in _delete_outputs(orphaned_outputs):
                print(f"deleted {_display_path(output)}")
            snapshot = current
        return 0

    output_dir = Path(args.output_dir) if args.output_dir else None
    files = explicit_files or discover_puml_files()
    if not files and not args.delete_orphans:
        return 0

    if args.delete_orphans:
        source_files = _sync_source_files(explicit_files)
        rendered_outputs, deleted_outputs = _render_with_orphan_cleanup(
            files,
            source_files,
            plantuml_bin=args.plantuml_bin,
        )
    else:
        rendered_outputs = render_puml_files(files, output_dir=output_dir, plantuml_bin=args.plantuml_bin)
        deleted_outputs = []

    for output in rendered_outputs:
        print(f"rendered {_display_path(output)}")
    for output in deleted_outputs:
        print(f"deleted {_display_path(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
