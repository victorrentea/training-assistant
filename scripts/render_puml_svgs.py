#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import tempfile
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


def main() -> int:
    files = discover_puml_files(SEQUENCES_DIR)
    if not files:
        return 0

    for output in render_puml_files(files, SVG_DIR):
        print(f"rendered {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
