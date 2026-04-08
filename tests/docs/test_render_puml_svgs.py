import runpy
import subprocess
from pathlib import Path

import pytest

from scripts.render_puml_svgs import (
    check_render_sync,
    discover_puml_files,
    render_puml_files,
)


def _write_puml(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"@startuml\nA -> B : {label}\n@enduml\n", encoding="utf-8")


def test_discover_puml_files_ignores_svg_subdir_and_only_returns_top_level_files(tmp_path):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    ignored = svg_dir / "ignored.puml"

    _write_puml(first, "first")
    _write_puml(second, "second")
    _write_puml(ignored, "ignored")
    (sequences_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    assert discover_puml_files(sequences_dir) == [first, second]


def test_render_puml_files_writes_one_svg_per_source(tmp_path, monkeypatch):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.render_puml_svgs.shutil.which", lambda _bin: "/usr/bin/plantuml")

    def fake_run(cmd, check, capture_output, text):
        commands.append(cmd)
        output_dir = Path(cmd[cmd.index("-o") + 1])
        source = Path(cmd[-1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{source.stem}.svg").write_text(f"<svg>{source.stem}</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("scripts.render_puml_svgs.subprocess.run", fake_run)

    outputs = render_puml_files([first, second], svg_dir, plantuml_bin="plantuml")

    assert outputs == [svg_dir / "01-a.svg", svg_dir / "02-b.svg"]
    assert (svg_dir / "01-a.svg").read_text(encoding="utf-8") == "<svg>01-a</svg>"
    assert (svg_dir / "02-b.svg").read_text(encoding="utf-8") == "<svg>02-b</svg>"
    assert commands == [
        ["plantuml", "-tsvg", "-o", str(svg_dir), str(first)],
        ["plantuml", "-tsvg", "-o", str(svg_dir), str(second)],
    ]


def test_check_render_sync_reports_missing_and_stale_svgs(tmp_path, monkeypatch):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    third = sequences_dir / "03-c.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")
    _write_puml(third, "third")

    svg_dir.mkdir(parents=True, exist_ok=True)
    (svg_dir / "01-a.svg").write_text("<svg>01-a</svg>", encoding="utf-8")
    (svg_dir / "02-b.svg").write_text("<svg>stale</svg>", encoding="utf-8")

    monkeypatch.setattr("scripts.render_puml_svgs.shutil.which", lambda _bin: "/usr/bin/plantuml")

    def fake_run(cmd, check, capture_output, text):
        output_dir = Path(cmd[cmd.index("-o") + 1])
        source = Path(cmd[-1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{source.stem}.svg").write_text(f"<svg>{source.stem}</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("scripts.render_puml_svgs.subprocess.run", fake_run)

    stale = check_render_sync([first, second, third], svg_dir, plantuml_bin="plantuml")

    assert stale == [svg_dir / "02-b.svg", svg_dir / "03-c.svg"]


def test_script_entrypoint_renders_all_discovered_svgs(tmp_path, monkeypatch, capsys):
    repo_root = tmp_path
    sequences_dir = repo_root / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    original_resolve = Path.resolve

    def fake_resolve(self, *args, **kwargs):
        if self.name == "render_puml_svgs.py" and self.parent.name == "scripts":
            return repo_root / "scripts" / "render_puml_svgs.py"
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/plantuml")

    def fake_run(cmd, check, capture_output, text):
        output_dir = Path(cmd[cmd.index("-o") + 1])
        source = Path(cmd[-1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{source.stem}.svg").write_text(f"<svg>{source.stem}</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path("scripts/render_puml_svgs.py", run_name="__main__")

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.splitlines() == [
        "rendered docs/sequences/svg/01-a.svg",
        "rendered docs/sequences/svg/02-b.svg",
    ]
