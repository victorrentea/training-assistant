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

import sys
import time

from quiz_core import config_from_env, auto_generate, _get_json, DAEMON_POLL_INTERVAL


def run() -> None:
    config = config_from_env()
    print(f"[daemon] Started — polling {config.server_url} every {DAEMON_POLL_INTERVAL}s")
    print("[daemon] Press Ctrl+C to stop.\n")

    while True:
        try:
            data = _get_json(
                f"{config.server_url}/api/quiz-request",
                config.host_username, config.host_password,
            )
            req = data.get("request")
            if req:
                minutes = req.get("minutes", config.minutes)
                print(f"\n[daemon] Received quiz request: last {minutes} min")
                auto_generate(minutes, config)
        except RuntimeError as e:
            print(f"[daemon] Server unreachable: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n[daemon] Stopped.")
            return
        time.sleep(DAEMON_POLL_INTERVAL)


if __name__ == "__main__":
    run()
