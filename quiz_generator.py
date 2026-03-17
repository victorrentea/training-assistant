#!/usr/bin/env python3
"""
Quiz Generator — interactive CLI for the Workshop Live Interaction Tool.

Reads the last N minutes of transcription, generates a debate-triggering
poll question via Claude, lets you preview/refine it, then posts it live.

Usage:
    python3 quiz_generator.py [--minutes 30] [--dry-run]

All defaults come from secrets.env / environment variables.
Run quiz_daemon.py instead if you want background/automated mode.
"""

import argparse
import os
import sys

from quiz_core import (
    DEFAULT_MINUTES, DEFAULT_MODEL, DEFAULT_SERVER_URL,
    Config, load_secrets_env,
    load_transcription_files, extract_last_n_minutes,
    generate_quiz, refine_option, generate_topic_prompt,
    print_quiz, post_poll, open_poll, copy_to_clipboard,
)
from pathlib import Path


def parse_args() -> Config:
    load_secrets_env()
    parser = argparse.ArgumentParser(
        description="Generate a quiz from live transcription and post it as a workshop poll."
    )
    parser.add_argument("--folder",
        default=os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"))
    parser.add_argument("--minutes", type=int,
        default=int(os.environ.get("QUIZ_MINUTES", DEFAULT_MINUTES)))
    parser.add_argument("--server",
        default=os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL))
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    parser.add_argument("--model", default=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host-username", default=os.environ.get("HOST_USERNAME", "host"))
    parser.add_argument("--host-password", default=os.environ.get("HOST_PASSWORD", ""))
    args = parser.parse_args()

    if not args.api_key:
        parser.error("Anthropic API key required. Use --api-key or set ANTHROPIC_API_KEY.")
    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        parser.error(f"Folder not found: {folder}")

    return Config(
        folder=folder,
        minutes=args.minutes,
        server_url=args.server.rstrip("/"),
        api_key=args.api_key,
        model=args.model,
        dry_run=args.dry_run,
        host_username=args.host_username,
        host_password=args.host_password,
    )


def main() -> None:
    config = parse_args()

    # 1. Load transcription
    entries = load_transcription_files(config.folder)
    if not entries:
        print("[error] No transcription content found.", file=sys.stderr)
        sys.exit(1)

    # 2. Extract last N minutes
    text = extract_last_n_minutes(entries, config.minutes)
    if not text:
        print("[error] Extracted text is empty.", file=sys.stderr)
        sys.exit(1)
    print(f"[info] Extracted {len(text):,} characters covering the last {config.minutes} minutes")

    # 3. Generate quiz via Claude
    quiz = generate_quiz(text, config)

    # 4. Interactive feedback loop
    while True:
        print_quiz(quiz)

        if config.dry_run:
            print("[dry-run] Skipping post to server.")
            return

        n_opts = len(quiz["options"])
        opt_letters = "/".join(chr(65 + i) for i in range(n_opts))
        print(f"  [y] Post to server   [{opt_letters}] Replace that option   [n] Abort")
        try:
            answer = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

        if answer == "y":
            break
        elif answer == "n":
            print("Aborted.")
            return
        elif len(answer) == 1 and answer.isalpha() and (idx := ord(answer.upper()) - 65) < n_opts:
            opt_label = chr(65 + idx)
            try:
                feedback = input(f"Replace option {opt_label} with what? ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return
            if feedback:
                print("[info] Asking Claude to refine...")
                quiz = refine_option(quiz, f"replace option {opt_label} with: {feedback}", config)
        elif answer == "r":
            try:
                feedback = input("Describe the change: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return
            if feedback:
                print("[info] Asking Claude to refine...")
                quiz = refine_option(quiz, feedback, config)

    # 5. Post and open
    try:
        post_poll(quiz, config)
        print("[ok] Poll created.")
        open_poll(config)
        print("[ok] Poll opened for voting.")
        print(f"[ok] View results at: {config.server_url}/host")
    except RuntimeError as e:
        print(f"[error] Failed to post poll: {e}", file=sys.stderr)
        sys.exit(1)

    # 6. Topic summary → clipboard
    topic_prompt = generate_topic_prompt(text, config)
    if topic_prompt:
        if copy_to_clipboard(topic_prompt):
            print("\n[ok] Topic summary prompt copied to clipboard ✓")
        print("-" * 60)
        print(topic_prompt)
        print("-" * 60)


if __name__ == "__main__":
    main()
