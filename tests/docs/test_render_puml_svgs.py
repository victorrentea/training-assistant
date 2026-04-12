import subprocess
from pathlib import Path

import pytest

import scripts.render_puml_svgs as renderer


def _write_puml(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"@startuml\nA -> B : {label}\n@enduml\n", encoding="utf-8")


def test_discover_puml_files_ignores_svg_subdir_and_only_returns_top_level_files(tmp_path):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
    ignored = svg_dir / "ignored.puml"

    _write_puml(first, "first")
    _write_puml(second, "second")
    _write_puml(ignored, "ignored")
    (manual_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    assert renderer.discover_puml_files([manual_dir]) == [first, second]


def test_render_puml_files_writes_one_svg_per_source(tmp_path, monkeypatch):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
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
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
    third = manual_dir / "03-c.puml"
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

    stale = renderer.check_render_sync([first, second, third], plantuml_bin="plantuml")

    assert stale == [svg_dir / "02-b.svg", svg_dir / "03-c.svg"]


def test_changed_puml_files_returns_only_modified_sources(tmp_path):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
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
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    rendered: list[tuple[list[Path], Path, str]] = []

    def fake_render(files, output_dir=None, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        dest = output_dir if output_dir is not None else svg_dir
        return [dest / f"{path.stem}.svg" for path in files]

    monkeypatch.setattr(renderer, "render_puml_files", fake_render)

    assert renderer.main([]) == 0
    assert rendered == [([first, second], None, "plantuml")]
    assert capsys.readouterr().out.splitlines() == [
        "rendered docs/sequences/manual/svg/01-a.svg",
        "rendered docs/sequences/manual/svg/02-b.svg",
    ]


def test_main_default_mode_renders_only_explicit_paths(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    def fail_discover(_puml_dirs=None):
        raise AssertionError("discover_puml_files should not be called when paths are provided")

    captured: list[tuple[list[Path], Path | None, str]] = []

    def fake_render(files, output_dir=None, plantuml_bin="plantuml"):
        captured.append((list(files), output_dir, plantuml_bin))
        dest = output_dir if output_dir is not None else svg_dir
        return [dest / f"{path.stem}.svg" for path in files]

    monkeypatch.setattr(renderer, "discover_puml_files", fail_discover)
    monkeypatch.setattr(renderer, "render_puml_files", fake_render)

    assert renderer.main(["--plantuml-bin", "custom-plantuml", str(second)]) == 0
    assert captured == [([second.resolve()], None, "custom-plantuml")]
    assert capsys.readouterr().out.splitlines() == ["rendered docs/sequences/manual/svg/02-b.svg"]


def test_main_check_mode_returns_one_and_prints_stale_paths(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    source = manual_dir / "01-a.puml"
    stale_svg = svg_dir / "01-a.svg"
    _write_puml(source, "first")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])
    monkeypatch.setattr(renderer, "check_render_sync", lambda files, plantuml_bin="plantuml": [stale_svg])

    assert renderer.main(["--check"]) == 1
    assert capsys.readouterr().out.splitlines() == ["stale or missing: docs/sequences/manual/svg/01-a.svg"]


def test_main_check_mode_returns_zero_when_svg_matches(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    source = manual_dir / "01-a.puml"
    _write_puml(source, "first")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])
    monkeypatch.setattr(renderer, "check_render_sync", lambda files, plantuml_bin="plantuml": [])

    assert renderer.main(["--check"]) == 0
    assert capsys.readouterr().out == ""


def test_main_check_mode_reports_orphaned_svgs(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    orphan_svg = svg_dir / "orphan.svg"
    orphan_svg.parent.mkdir(parents=True, exist_ok=True)
    orphan_svg.write_text("<svg>orphan</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    assert renderer.main(["--check"]) == 1
    assert capsys.readouterr().out.splitlines() == ["orphaned: docs/sequences/manual/svg/orphan.svg"]


def test_main_delete_orphans_mode_keeps_orphans_when_render_fails(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    source = manual_dir / "01-a.puml"
    orphan_svg = svg_dir / "orphan.svg"
    _write_puml(source, "first")
    orphan_svg.parent.mkdir(parents=True, exist_ok=True)
    orphan_svg.write_text("<svg>orphan</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])
    monkeypatch.setattr(renderer, "render_puml_files", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("plantuml failed")))

    with pytest.raises(SystemExit, match="plantuml failed"):
        renderer.main(["--delete-orphans"])

    assert orphan_svg.exists()
    assert capsys.readouterr().out == ""


def test_main_watch_mode_rediscovers_new_files_when_starting_empty(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    manual_dir.mkdir(parents=True, exist_ok=True)
    new_file = manual_dir / "01-a.puml"

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    rendered: list[tuple[list[Path], Path | None, str]] = []

    def fake_render(files, output_dir=None, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        dest = output_dir if output_dir is not None else svg_dir
        return [dest / f"{path.stem}.svg" for path in files]

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

    assert rendered == [([new_file], None, "plantuml")]
    assert capsys.readouterr().out.splitlines() == ["rendered docs/sequences/manual/svg/01-a.svg"]


def test_main_watch_mode_cleans_startup_orphans_without_rendering(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    svg_dir.mkdir(parents=True, exist_ok=True)
    orphan_svg = svg_dir / "orphan.svg"
    orphan_svg.write_text("<svg>orphan</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])
    monkeypatch.setattr(
        renderer,
        "render_puml_files",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render_puml_files should not be called")),
    )
    monkeypatch.setattr(renderer.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        renderer.main(["--watch"])

    assert not orphan_svg.exists()
    assert capsys.readouterr().out.splitlines() == ["deleted docs/sequences/manual/svg/orphan.svg"]


def test_main_watch_mode_preserves_explicit_external_source_output(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    external_source = tmp_path / "external" / "external-flow.puml"
    _write_puml(external_source, "external")
    # External source SVG lives next to its source (external/svg/), not in manual/svg/
    external_svg_dir = tmp_path / "external" / "svg"
    external_svg_dir.mkdir(parents=True, exist_ok=True)
    external_svg = external_svg_dir / "external-flow.svg"
    external_svg.write_text("<svg>keep</svg>", encoding="utf-8")
    # An unrelated SVG in manual/svg/ is an orphan and should be deleted
    svg_dir.mkdir(parents=True, exist_ok=True)
    orphan_svg = svg_dir / "orphan.svg"
    orphan_svg.write_text("<svg>delete</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])
    monkeypatch.setattr(
        renderer,
        "render_puml_files",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render_puml_files should not be called")),
    )

    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float):
        sleep_calls["count"] += 1
        if sleep_calls["count"] == 1:
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(renderer.time, "sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        renderer.main(["--watch", str(external_source)])

    assert external_svg.exists()
    assert not orphan_svg.exists()
    assert capsys.readouterr().out.splitlines() == ["deleted docs/sequences/manual/svg/orphan.svg"]


def test_main_watch_mode_rerenders_only_changed_files(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    svg_dir = manual_dir / "svg"
    first = manual_dir / "01-a.puml"
    second = manual_dir / "02-b.puml"
    _write_puml(first, "first")
    _write_puml(second, "second")
    svg_dir.mkdir(parents=True, exist_ok=True)
    orphan_svg = svg_dir / "01-a.svg"
    orphan_svg.write_text("<svg>orphan</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    rendered: list[tuple[list[Path], Path | None, str]] = []

    def fake_render(files, output_dir=None, plantuml_bin="plantuml"):
        rendered.append((list(files), output_dir, plantuml_bin))
        dest = output_dir if output_dir is not None else svg_dir
        return [dest / f"{path.stem}.svg" for path in files]

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

    assert not orphan_svg.exists()
    assert rendered == [([second.resolve()], None, "plantuml")]
    assert capsys.readouterr().out.splitlines() == [
        "rendered docs/sequences/manual/svg/02-b.svg",
        "deleted docs/sequences/manual/svg/01-a.svg",
    ]


def test_main_watch_mode_keeps_orphan_svg_when_render_fails(tmp_path, monkeypatch, capsys):
    manual_dir = tmp_path / "docs" / "sequences" / "manual"
    external_source = tmp_path / "external" / "01-a.puml"
    _write_puml(external_source, "first")
    # External source SVG lives next to its source (external/svg/)
    external_svg_dir = tmp_path / "external" / "svg"
    external_svg_dir.mkdir(parents=True, exist_ok=True)
    external_svg = external_svg_dir / "01-a.svg"
    external_svg.write_text("<svg>still-here</svg>", encoding="utf-8")

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "PUML_DIRS", [manual_dir])

    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float):
        sleep_calls["count"] += 1
        if sleep_calls["count"] == 1:
            _write_puml(external_source, "changed")
            return
        raise KeyboardInterrupt

    def failing_render(files, output_dir=None, plantuml_bin="plantuml"):
        raise SystemExit("plantuml failed")

    monkeypatch.setattr(renderer, "render_puml_files", failing_render)
    monkeypatch.setattr(renderer.time, "sleep", fake_sleep)

    with pytest.raises(SystemExit, match="plantuml failed"):
        renderer.main(["--watch", str(external_source)])

    assert external_svg.exists()
    assert capsys.readouterr().out == ""
