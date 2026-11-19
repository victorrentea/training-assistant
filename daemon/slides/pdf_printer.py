"""PowerPoint prints slides into a PDF file, with no dialog, through a printer of our own.

Google's and Microsoft's converters lay a deck out differently from PowerPoint on the Mac
(other emoji, other line breaks: a line that fits here wraps there and pushes the last
bullet off the slide), so the only faithful PDF is PowerPoint's own. Its scripted
"print out" takes a slide range but always goes to the default printer and ignores
"print to file". So: macOS's `ippeveprinter` runs as a printer that writes what it
receives into a folder, a CUPS queue points at it, and for the moment of the print that
queue is the default printer. The trainer sees a very brief flash (Victor, 2026-11-19:
acceptable); nothing is saved, nothing takes the focus.
"""
from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from daemon import log

QUEUE = "Interact_PDF"
_PORT = 8631
_HOME = Path.home() / "Library" / "Caches" / "training-assistant" / "slides-printer"
_SPOOL = _HOME / "spool"
# The printer that was the default before a print, kept on disk until it is put back:
# a daemon killed mid-print must not leave the trainer's real printer replaced.
_PREVIOUS_DEFAULT = _HOME / "previous-default-printer"
_POWERPOINT = "Microsoft PowerPoint"
_PRINT_TIMEOUT_S = 90.0

_server: subprocess.Popen | None = None
_lock = threading.Lock()


class PrintUnavailable(RuntimeError):
    """This deck cannot be printed right now; the caller falls back to Google's PDF."""


def supported() -> bool:
    return (
        sys.platform == "darwin"
        and os.environ.get("SLIDES_LOCAL_PRINT", "1") != "0"
        and os.environ.get("DAEMON_ADAPTER") != "stub"
        and shutil.which("ippeveprinter") is not None
        and (shutil.which("gs") is not None or Path("/opt/homebrew/bin/gs").exists())
    )


def _run(*command: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _default_printer() -> str | None:
    out = _run("lpstat", "-d").stdout
    return out.split(":", 1)[1].strip() if ":" in out else None


def _restore_default() -> None:
    if not _PREVIOUS_DEFAULT.exists():
        return
    previous = _PREVIOUS_DEFAULT.read_text(encoding="utf-8").strip()
    if previous and previous != QUEUE:
        _run("lpoptions", "-d", previous)
    _PREVIOUS_DEFAULT.unlink(missing_ok=True)


def _ensure_printer() -> None:
    global _server
    _SPOOL.mkdir(parents=True, exist_ok=True)
    _restore_default()  # left behind by a daemon that died mid-print
    if (_server is None or _server.poll() is not None) and not _listening():
        _server = subprocess.Popen(
            ["ippeveprinter", "-d", str(_SPOOL), "-k", "-p", str(_PORT), "-r", "off",
             "-f", "application/pdf", "-s", "0,0", "Interact PDF"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        atexit.register(shutdown)
        time.sleep(1.5)
        if _server.poll() is not None:
            raise PrintUnavailable(f"ippeveprinter did not start (is port {_PORT} taken?)")
    if _run("lpstat", "-p", QUEUE).returncode != 0:
        added = _run("lpadmin", "-p", QUEUE, "-E", "-v", f"ipp://localhost:{_PORT}/ipp/print", "-m", "everywhere")
        if added.returncode != 0:
            raise PrintUnavailable(f"Could not add the print queue: {added.stderr.strip()}")


def _listening() -> bool:
    """A printer left by a daemon that was killed still serves the same folder: use it."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", _PORT)) == 0


def recover() -> None:
    """At daemon start: put the trainer's default printer back if a print was cut short."""
    if supported():
        _restore_default()


def shutdown() -> None:
    """The queue goes with the daemon: a printer with nothing behind it would swallow
    whatever the trainer sent to it."""
    global _server
    _restore_default()
    if _server is not None and _server.poll() is None:
        _server.terminate()
        _run("lpadmin", "-x", QUEUE)
    _server = None


def open_decks() -> tuple[list[str], bool]:
    """The presentations open in PowerPoint, and whether a slide show is running.
    Never starts PowerPoint: asking an app that is not running would launch it."""
    if _run("pgrep", "-x", _POWERPOINT).returncode != 0:
        return [], False
    script = (
        f'tell application "{_POWERPOINT}"\n'
        # Not a repeat over `presentations`: that loop never comes back (PowerPoint 16.114).
        "  set AppleScript's text item delimiters to linefeed\n"
        '  return ((name of every presentation) as text) & "|" & (count of slide show windows)\n'
        "end tell"
    )
    result = _run("osascript", "-e", script)
    if result.returncode != 0:
        log.error("slides", f"PowerPoint did not answer: {result.stderr.strip()[:200]}")
        return [], False
    names, _, shows = result.stdout.rpartition("|")
    return [n for n in names.splitlines() if n.strip()], shows.strip() not in ("", "0")


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _wait_for_new_pdf(before: set[Path], timeout: float) -> Path:
    deadline = time.time() + timeout
    while time.time() < deadline:
        fresh = sorted(set(_SPOOL.glob("*.pdf")) - before)
        if fresh:
            size = fresh[0].stat().st_size
            time.sleep(0.7)
            if size > 0 and fresh[0].stat().st_size == size:
                return fresh[0]
        else:
            time.sleep(0.3)
    raise PrintUnavailable("PowerPoint's print never arrived")


def print_slides(deck_name: str, ranges: list[tuple[int, int]] | None) -> list[Path]:
    """One PDF per range of slides (None: the whole deck), as PowerPoint printed them:
    each slide in the middle of a sheet of paper. The caller deletes the files."""
    with _lock:
        _ensure_printer()
        for stale in _SPOOL.glob("*.pdf"):
            stale.unlink(missing_ok=True)
        previous = _default_printer()
        _PREVIOUS_DEFAULT.write_text(previous or "", encoding="utf-8")
        printed: list[Path] = []
        try:
            if _run("lpoptions", "-d", QUEUE).returncode != 0 or _default_printer() != QUEUE:
                raise PrintUnavailable("Could not make the PDF queue the default printer")
            for first, last in ranges or [(0, 0)]:
                before = set(_SPOOL.glob("*.pdf"))
                pages = f" from {first} to {last}" if first else ""
                script = (
                    f'tell application "{_POWERPOINT}" to print out presentation '
                    f"{_quoted(deck_name)}{pages} showDialog false"
                )
                result = _run("osascript", "-e", script, timeout=60.0)
                if result.returncode != 0:
                    raise PrintUnavailable(f"PowerPoint refused to print: {result.stderr.strip()[:200]}")
                printed.append(_wait_for_new_pdf(before, _PRINT_TIMEOUT_S))
        finally:
            _restore_default()
            # The queue keeps what it printed: nothing to keep here once the files are taken.
            _run("cancel", "-a", QUEUE)
        return printed
