import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_importlinter_from_structurizr.py"
WORKSPACE_DSL = ROOT / "docs" / "structurizr" / "workspace.dsl"
CONFIG_PATH = ROOT / "docs" / "structurizr" / "out" / "importlinter.ini"
REPORT_PATH = ROOT / "docs" / "structurizr" / "out" / "importlinter-report.json"


def _run_generator(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--workspace", str(WORKSPACE_DSL), *extra_args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_generator_outputs_importlinter_config_to_stdout():
    completed = _run_generator("--stdout")
    assert completed.returncode == 0, completed.stderr
    assert "[importlinter]" in completed.stdout
    assert "[importlinter:contract:" in completed.stdout


def test_generator_writes_config_and_report_files():
    completed = _run_generator("--output", str(CONFIG_PATH), "--report", str(REPORT_PATH))
    assert completed.returncode == 0, completed.stderr
    assert CONFIG_PATH.exists()
    assert REPORT_PATH.exists()
    config_content = CONFIG_PATH.read_text(encoding="utf-8")
    assert "root_package = railway" in config_content

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert "resolved_components" in report
    assert "unresolved_components" in report


def test_import_linter_passes_with_generated_config():
    completed = _run_generator("--output", str(CONFIG_PATH), "--report", str(REPORT_PATH))
    assert completed.returncode == 0, completed.stderr

    lint = subprocess.run(
        ["uv", "run", "--extra", "dev", "lint-imports", "--config", str(CONFIG_PATH)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert lint.returncode == 0, lint.stdout + "\n" + lint.stderr


def test_generated_importlinter_artifacts_are_fresh():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_config = Path(tmpdir) / "importlinter.ini"
        tmp_report = Path(tmpdir) / "report.json"
        report_run = _run_generator("--output", str(tmp_config), "--report", str(tmp_report))
        assert report_run.returncode == 0, report_run.stderr
        committed_config = CONFIG_PATH.read_text(encoding="utf-8")
        generated_config = tmp_config.read_text(encoding="utf-8")
        assert committed_config == generated_config, (
            "docs/structurizr/out/importlinter.ini is stale.\n"
            "Run: python3 scripts/generate_importlinter_from_structurizr.py"
        )

        committed_report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        generated_report = json.loads(tmp_report.read_text(encoding="utf-8"))
        assert committed_report == generated_report, (
            "docs/structurizr/out/importlinter-report.json is stale.\n"
            "Run: python3 scripts/generate_importlinter_from_structurizr.py"
        )
