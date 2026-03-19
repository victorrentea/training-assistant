#!/usr/bin/env python3
"""
Quiz Daemon — runs in the background on the trainer's Mac.

Polls the workshop server for quiz generation requests triggered from the
host panel, then runs the full generate → post → open flow automatically.

Usage:
    python3 quiz_daemon.py

All configuration is read from secrets.env and environment variables:
    ANTHROPIC_API_KEY       Claude API key (required)
    WORKSHOP_SERVER_URL     e.g. https://interact.victorrentea.ro
    HOST_USERNAME / HOST_PASSWORD
    TRANSCRIPTION_FOLDER    path to transcription files
"""

import os
import signal
import sys
import time
from pathlib import Path

from quiz_core import (
    config_from_env, auto_generate, auto_generate_topic, auto_refine,
    _get_json, DAEMON_POLL_INTERVAL,
)

_PID_FILE = Path("/tmp/quiz_daemon.pid")


def _kill_previous() -> None:
    if not _PID_FILE.exists():
        return
    try:
        pid = int(_PID_FILE.read_text().strip())
        if pid == os.getpid():
            return
        os.kill(pid, signal.SIGTERM)
        print(f"[daemon] Killed previous instance (PID {pid})")
        time.sleep(0.5)
    except (ValueError, ProcessLookupError, PermissionError):
        pass  # stale or already gone
    _PID_FILE.unlink(missing_ok=True)


def run() -> None:
    _kill_previous()
    _PID_FILE.write_text(str(os.getpid()))

    def _cleanup(*_):
        _PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    config = config_from_env()

    # Start background material indexer
    materials_folder_str = os.environ.get("MATERIALS_FOLDER",
        str(Path(__file__).parent / "materials"))
    materials_folder = Path(materials_folder_str).expanduser()
    if materials_folder.exists():
        from daemon.indexer import start_indexer
        start_indexer(materials_folder)
    else:
        print(f"[daemon] MATERIALS_FOLDER not found: {materials_folder} — indexer disabled", file=sys.stderr)

    print(f"[daemon] Started — polling {config.server_url} every {DAEMON_POLL_INTERVAL}s")
    print("[daemon] Press Ctrl+C to stop.\n")

    # Session state: the transcript text used to generate the current preview
    last_text: str | None = None
    last_quiz: dict | None = None

    while True:
        try:
            # ── Check for new quiz generation request ──
            data = _get_json(
                f"{config.server_url}/api/quiz-request",
                config.host_username, config.host_password,
            )
            req = data.get("request")
            if req:
                topic = req.get("topic")
                minutes = req.get("minutes")
                if topic:
                    print(f"\n[daemon] Topic request: '{topic}'")
                    result = auto_generate_topic(topic, config)
                else:
                    minutes = minutes or config.minutes
                    print(f"\n[daemon] Transcript request: last {minutes} min")
                    result = auto_generate(minutes, config)
                if result:
                    last_quiz, last_text = result
                else:
                    last_quiz, last_text = None, None

            # ── Check for refine request ──
            refine_data = _get_json(
                f"{config.server_url}/api/quiz-refine",
                config.host_username, config.host_password,
            )
            refine_req = refine_data.get("request")
            if refine_req:
                target = refine_req.get("target", "question")
                # Use server-side preview as current quiz (in case host re-opened page)
                current_quiz = refine_data.get("preview") or last_quiz
                if current_quiz and last_text:
                    print(f"\n[daemon] Refine request: target={target}")
                    updated = auto_refine(target, current_quiz, last_text, config)
                    if updated:
                        last_quiz = updated
                else:
                    from quiz_core import post_status
                    post_status("error", "No conversation context — please generate a question first.", config)

        except RuntimeError as e:
            print(f"[daemon] Server unreachable: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            _PID_FILE.unlink(missing_ok=True)
            print("\n[daemon] Stopped.")
            return
        time.sleep(DAEMON_POLL_INTERVAL)


if __name__ == "__main__":
    run()
