#!/usr/bin/env python3
"""Clipboard cleanup daemon using Claude Haiku.

Listens for Cmd+Ctrl+V, reads clipboard, sends to Claude for grammar/filler cleanup,
then undoes the original paste and re-pastes the cleaned version.
"""

import os
import signal
import sys
import threading
import time
from datetime import datetime

import anthropic
import pyperclip
from pynput.keyboard import Controller, GlobalHotKeys, Key

MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 2
MAX_INPUT_CHARS = 5000
CLEANUP_PROMPT = (
    "Fix grammar, punctuation, and spelling errors.\n"
    "Remove filler words and false starts from speech-to-text output.\n"
    "Synthesize verbose text into concise form while preserving all meaning.\n"
    "Detect the input language and respond in the same language.\n"
    "Return ONLY the cleaned text, nothing else."
)

client = anthropic.Anthropic()
keyboard_controller = Controller()
lock = threading.Lock()


def log(message: str) -> None:
    """Print a timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def clean_text(text: str) -> str | None:
    """Send text to Claude Haiku for cleanup. Returns cleaned text or None on failure."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": text}],
            system=CLEANUP_PROMPT,
            timeout=TIMEOUT,
        )
        return response.content[0].text
    except Exception as e:
        log(f"API error: {e}")
        return None


def handle_hotkey() -> None:
    """Handle the cleanup hotkey press."""
    if not lock.acquire(blocking=False):
        return
    try:
        start = time.time()

        text = pyperclip.paste()
        if not text or not text.strip():
            log("Skipped: clipboard is empty")
            return
        if len(text) > MAX_INPUT_CHARS:
            log(f"Skipped: text too long ({len(text)} chars > {MAX_INPUT_CHARS})")
            return

        log(f"Cleaning {len(text)} chars...")
        cleaned = clean_text(text)

        if cleaned is None:
            log("Failed: no response from API")
            return

        # Undo the original paste
        keyboard_controller.press(Key.cmd)
        keyboard_controller.press('z')
        keyboard_controller.release('z')
        keyboard_controller.release(Key.cmd)
        time.sleep(0.1)

        # Write cleaned text to clipboard and paste
        pyperclip.copy(cleaned)
        time.sleep(0.05)

        keyboard_controller.press(Key.cmd)
        keyboard_controller.press('v')
        keyboard_controller.release('v')
        keyboard_controller.release(Key.cmd)

        elapsed_ms = int((time.time() - start) * 1000)
        log(f"Done ({len(text)} -> {len(cleaned)} chars, {elapsed_ms}ms)")
    except Exception as e:
        log(f"Failed: {e}")
    finally:
        lock.release()


def main() -> None:
    """Start the clipboard cleanup daemon."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set")
        sys.exit(1)

    log("Clipboard cleaner started. Press Cmd+Ctrl+V to clean clipboard text.")

    hotkeys = GlobalHotKeys({
        '<cmd>+<ctrl>+v': lambda: threading.Thread(target=handle_hotkey, daemon=True).start()
    })

    def on_sigint(signum, frame):
        log("Shutting down...")
        hotkeys.stop()

    signal.signal(signal.SIGINT, on_sigint)

    hotkeys.start()
    hotkeys.join()


if __name__ == "__main__":
    main()
