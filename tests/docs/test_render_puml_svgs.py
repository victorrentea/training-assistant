import subprocess
from pathlib import Path

import pytest

import scripts.render_puml_svgs as renderer


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

    assert renderer.discover_puml_files(sequences_dir) == [first, second]


def test_render_puml_files_writes_one_svg_per_source(tmp_path, monkeypatch):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    commands: list[list[str]] = []
    monkeypatch.setattr(renderer.shutil, "which", lambda _bin: "/usr/bin/plantuml")

    def fake_run(cmd, check, capture_output, text):
        commands.append(cmd)
        output_dir = Path(cmd[cmd.index("-o") + 1])
        source = Path(cmd[-1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{source.stem}.svg").write_text(f"<svg>{source.stem}</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(renderer.subprocess, "run", fake_run)

    outputs = renderer.render_puml_files([first, second], svg_dir, plantuml_bin="plantuml")

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

    monkeypatch.setattr(renderer.shutil, "which", lambda _bin: "/usr/bin/plantuml")

    def fake_run(cmd, check, capture_output, text):
        output_dir = Path(cmd[cmd.index("-o") + 1])
        source = Path(cmd[-1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{source.stem}.svg").write_text(f"<svg>{source.stem}</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(renderer.subprocess, "run", fake_run)

    stale = renderer.check_render_sync([first, second, third], svg_dir, plantuml_bin="plantuml")

    assert stale == [svg_dir / "02-b.svg", svg_dir / "03-c.svg"]


def test_changed_puml_files_returns_only_modified_sources(tmp_path):
    sequences_dir = tmp_path / "docs" / "sequences"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    before = renderer.build_input_snapshot([first, second])
    _write_puml(second, "changed")
    after = renderer.build_input_snapshot([first, second])

    assert renderer.changed_puml_files(before, after) == [second]


def test_parse_args_rejects_check_and_watch_together(capsys):
    with pytest.raises(SystemExit) as excinfo:
        renderer.parse_args(["--check", "--watch"])

    assert excinfo.value.code == 2
    assert "--watch" in capsys.readouterr().err


def test_main_default_mode_renders_discovered_files(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)

    rendered: list[tuple[list[Path], Path, str]] = []

    def fake_render(files, output_dir, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        return [output_dir / f"{path.stem}.svg" for path in files]

    monkeypatch.setattr(renderer, "render_puml_files", fake_render)

    assert renderer.main([]) == 0
    assert rendered == [([first, second], svg_dir, "plantuml")]
    assert capsys.readouterr().out.splitlines() == [
        "rendered docs/sequences/svg/01-a.svg",
        "rendered docs/sequences/svg/02-b.svg",
    ]


def test_main_default_mode_renders_only_explicit_paths(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)

    def fail_discover(_sequences_dir: Path):
        raise AssertionError("discover_puml_files should not be called when paths are provided")

    captured: list[tuple[list[Path], Path, str]] = []

    def fake_render(files, output_dir, plantuml_bin="plantuml"):
        captured.append((list(files), output_dir, plantuml_bin))
        return [output_dir / f"{path.stem}.svg" for path in files]

    monkeypatch.setattr(renderer, "discover_puml_files", fail_discover)
    monkeypatch.setattr(renderer, "render_puml_files", fake_render)

    assert renderer.main(["--plantuml-bin", "custom-plantuml", str(second)]) == 0
    assert captured == [([second.resolve()], svg_dir, "custom-plantuml")]
    assert capsys.readouterr().out.splitlines() == ["rendered docs/sequences/svg/02-b.svg"]


def test_main_check_mode_returns_one_and_prints_stale_paths(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    source = sequences_dir / "01-a.puml"
    stale_svg = svg_dir / "01-a.svg"
    _write_puml(source, "first")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)
    monkeypatch.setattr(renderer, "check_render_sync", lambda files, output_dir, plantuml_bin="plantuml": [stale_svg])

    assert renderer.main(["--check"]) == 1
    assert capsys.readouterr().out.splitlines() == ["stale or missing: docs/sequences/svg/01-a.svg"]


def test_main_check_mode_returns_zero_when_svg_matches(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    source = sequences_dir / "01-a.puml"
    _write_puml(source, "first")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)
    monkeypatch.setattr(renderer, "check_render_sync", lambda files, output_dir, plantuml_bin="plantuml": [])

    assert renderer.main(["--check"]) == 0
    assert capsys.readouterr().out == ""


def test_main_watch_mode_rediscovers_new_files_when_starting_empty(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    sequences_dir.mkdir(parents=True, exist_ok=True)
    new_file = sequences_dir / "01-a.puml"

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)

    rendered: list[tuple[list[Path], Path, str]] = []

    def fake_render(files, output_dir, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        return [output_dir / f"{path.stem}.svg" for path in files]

    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float):
        sleep_calls["count"] += 1
        if sleep_calls["count"] == 1:
            _write_puml(new_file, "new")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(renderer, "render_puml_files", fake_render)
    monkeypatch.setattr(renderer.time, "sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        renderer.main(["--watch"])

    assert rendered == [([new_file], svg_dir, "plantuml")]
    assert capsys.readouterr().out.splitlines() == ["rendered docs/sequences/svg/01-a.svg"]


def test_main_watch_mode_rerenders_only_changed_files(tmp_path, monkeypatch, capsys):
    sequences_dir = tmp_path / "docs" / "sequences"
    svg_dir = sequences_dir / "svg"
    first = sequences_dir / "01-a.puml"
    second = sequences_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SEQUENCES_DIR", sequences_dir)
    monkeypatch.setattr(renderer, "SVG_DIR", svg_dir)

    rendered: list[tuple[list[Path], Path, str]] = []

    def fake_render(files, output_dir, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        return [output_dir / f"{path.stem}.svg" for path in files]

    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float):
        sleep_calls["count"] += 1
        if sleep_calls["count"] == 1:
            first.unlink()
            _write_puml(second, "changed")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(renderer, "render_puml_files", fake_render)
    monkeypatch.setattr(renderer.time, "sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        renderer.main(["--watch", str(first), str(second)])

    assert rendered == [([second.resolve()], svg_dir, "plantuml")]
    assert capsys.readouterr().out.splitlines() == ["rendered docs/sequences/svg/02-b.svg"]
