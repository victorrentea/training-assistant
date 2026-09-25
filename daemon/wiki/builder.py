"""Build a session's wiki/ folder into a static Quartz site.

The wiki is an Obsidian vault written by the training-summarizer skill into the
session folder. Quartz (open source, installed by scripts/setup-quartz.sh) turns it
into browsable HTML with Obsidian's graph view, backlinks and search. One build per
session, from that session's folder only — nothing from other sessions can leak in.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "quartz"
BUILD_TIMEOUT_S = 300

# Same exclusions as the materials zip, plus the vault's own settings folder.
_IGNORED = shutil.ignore_patterns(".obsidian", ".DS_Store", "Icon", "Icon\r", "~$*")


class WikiBuildError(RuntimeError):
    """Quartz is missing or the build failed."""


def quartz_dir() -> Path:
    return Path(
        os.environ.get("QUARTZ_DIR") or Path.home() / ".cache" / "training-assistant" / "quartz"
    ).expanduser()


def find_wiki_dir(session_folder: Path | None) -> Path | None:
    if session_folder is None:
        return None
    wiki = session_folder / "wiki"
    return wiki if wiki.is_dir() else None


def _markdown_files(wiki_dir: Path):
    for path in wiki_dir.rglob("*.md"):
        if ".obsidian" not in path.relative_to(wiki_dir).parts:
            yield path


def fingerprint(wiki_dir: Path) -> tuple[int, int, int] | None:
    """(file count, newest mtime_ns, total bytes) of the vault's pages; None if it has none.

    A stat per page — cheap enough to poll every few seconds.
    """
    count = newest = total = 0
    for path in _markdown_files(wiki_dir):
        try:
            st = path.stat()
        except OSError:
            continue
        count += 1
        newest = max(newest, st.st_mtime_ns)
        total += st.st_size
    return (count, newest, total) if count else None


def _prepare_quartz(qdir: Path) -> None:
    if not (qdir / "node_modules").is_dir():
        raise WikiBuildError(f"Quartz is not installed in {qdir} — run scripts/setup-quartz.sh")
    shutil.copy(ASSETS_DIR / "quartz.config.ts", qdir)
    shutil.copy(ASSETS_DIR / "quartz.layout.ts", qdir)
    shutil.copy(ASSETS_DIR / "custom.scss", qdir / "quartz" / "styles" / "custom.scss")
    patch = subprocess.run(
        [sys.executable, str(ASSETS_DIR / "patch-graph.py"),
         str(qdir / "quartz" / "components" / "scripts" / "graph.inline.ts")],
        capture_output=True, text=True,
    )
    if patch.returncode != 0:
        raise WikiBuildError(f"Graph patch failed: {patch.stderr.strip() or patch.stdout.strip()}")


def build_site(wiki_dir: Path, title: str, out_dir: Path) -> None:
    """Render wiki_dir into out_dir with Quartz. Raises WikiBuildError."""
    qdir = quartz_dir()
    _prepare_quartz(qdir)
    with tempfile.TemporaryDirectory(prefix="wiki-content-") as tmp:
        content = Path(tmp) / "content"
        shutil.copytree(wiki_dir, content, ignore=_IGNORED)
        try:
            result = subprocess.run(
                # nice: the build must never make the trainer's machine stutter mid-demo
                ["nice", "-n", "10", "npx", "quartz", "build", "-d", str(content), "-o", str(out_dir)],
                cwd=qdir,
                env={**os.environ, "WIKI_TITLE": title},
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise WikiBuildError(f"Quartz build timed out after {BUILD_TIMEOUT_S}s") from exc
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-15:])
        raise WikiBuildError(f"Quartz build failed:\n{tail}")
    _use_home_as_landing_page(wiki_dir, out_dir)


def _use_home_as_landing_page(wiki_dir: Path, out_dir: Path) -> None:
    """The summarizer names the vault's entry page Home.md, not index.md.

    Quartz's site root is index.md. Copying Home's page over the root (same folder
    depth, so its relative links still resolve) keeps Home as the hub node in the
    graph, which renaming it would lose.
    """
    if (wiki_dir / "index.md").exists():
        return
    home = out_dir / "Home.html"
    if home.is_file():
        shutil.copy(home, out_dir / "index.html")


def zip_site(site_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(site_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(site_dir).as_posix())
    return buffer.getvalue()
