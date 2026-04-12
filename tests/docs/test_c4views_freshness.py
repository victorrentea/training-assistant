"""Ensure committed C4 view exports match the current docs/c4model.dsl.

Requires Docker (structurizr/structurizr image).  Skipped when Docker is unavailable.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DSL = ROOT / "docs" / "c4model.dsl"
VIEWS_DIR = ROOT / "docs" / "c4views"
IMAGE = "structurizr/structurizr"
# Temp dir inside the repo so Docker volume mount can see it
_TEMP_EXPORT = ROOT / ".c4views-tmp"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _export(fmt: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{ROOT}:/usr/local/structurizr",
            IMAGE,
            "export",
            "-workspace", "docs/c4model.dsl",
            "-format", fmt,
            "-output", str(output_dir.relative_to(ROOT)),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


@pytest.fixture(autouse=True)
def _cleanup_temp():
    yield
    if _TEMP_EXPORT.exists():
        shutil.rmtree(_TEMP_EXPORT)


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestC4ViewsFreshness:
    def test_puml_exports_are_fresh(self):
        _export("plantuml/c4plantuml", _TEMP_EXPORT)
        for generated in sorted(_TEMP_EXPORT.glob("structurizr-*.puml")):
            committed = VIEWS_DIR / generated.name
            assert committed.exists(), (
                f"Missing committed file: docs/c4views/{generated.name}\n"
                "Run: bash scripts/export_c4views.sh"
            )
            assert committed.read_text() == generated.read_text(), (
                f"docs/c4views/{generated.name} is stale.\n"
                "Run: bash scripts/export_c4views.sh"
            )

    def test_mermaid_exports_are_fresh(self):
        _export("mermaid", _TEMP_EXPORT)
        for generated in sorted(_TEMP_EXPORT.glob("structurizr-*.mmd")):
            committed = VIEWS_DIR / generated.name
            assert committed.exists(), (
                f"Missing committed file: docs/c4views/{generated.name}\n"
                "Run: bash scripts/export_c4views.sh"
            )
            assert committed.read_text() == generated.read_text(), (
                f"docs/c4views/{generated.name} is stale.\n"
                "Run: bash scripts/export_c4views.sh"
            )
