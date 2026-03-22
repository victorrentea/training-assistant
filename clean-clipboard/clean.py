#!/usr/bin/env python3
"""Clipboard cleanup daemon using Claude Haiku and macOS CGEventTap.

Intercepts every Cmd+V at the system level to capture clipboard contents
(including ephemeral pastes from tools like Wispr Flow).
When the user presses Cmd+Ctrl+V, the last captured paste is cleaned via AI,
the original paste is undone, and the cleaned version is pasted in its place.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

import anthropic
from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGEventKeyDown,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
)

MODEL = "claude-haiku-4-5-20251001"
TIMEOUT_BASE = 2       # seconds for short text (< 200 chars)
TIMEOUT_PER_1K = 1.5   # extra seconds per 1000 chars
TIMEOUT_MAX = 15       # hard cap
MAX_INPUT_CHARS = 5000
CLEANUP_PROMPT = (
    "Fix grammar, punctuation, and spelling errors.\n"
    "Remove filler words and false starts from speech-to-text output.\n"
    "Synthesize verbose text into concise form while preserving all meaning.\n"
    "Detect the input language and respond in the same language.\n"
    "Return ONLY the cleaned text, nothing else."
)

# macOS virtual key codes
VK_V = 0x09
VK_Z = 0x06

client = anthropic.Anthropic(max_retries=0)
lock = threading.Lock()

# Stores the clipboard content captured at the moment of each Cmd+V
last_paste_text: str | None = None
last_paste_lock = threading.Lock()


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def get_clipboard() -> str:
    """Read clipboard using pbpaste (reliable on macOS)."""
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=1
        )
        return result.stdout
    except Exception:
        return ""


def set_clipboard(text: str) -> None:
    """Write to clipboard using pbcopy."""
    try:
        subprocess.run(
            ["pbcopy"], input=text, text=True, timeout=1
        )
    except Exception as e:
        log(f"pbcopy failed: {e}")


def simulate_keystroke(keycode: int, flags: int = 0) -> None:
    """Simulate a keystroke using AppleScript (most reliable on macOS)."""
    if keycode == VK_V and flags == kCGEventFlagMaskCommand:
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
            timeout=2,
        )
    elif keycode == VK_Z and flags == kCGEventFlagMaskCommand:
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "z" using command down'],
            timeout=2,
        )


def compute_timeout(text: str) -> float:
    """Variable timeout: 2s base + 1.5s per 1000 chars, capped at 15s."""
    return min(TIMEOUT_BASE + (len(text) / 1000) * TIMEOUT_PER_1K, TIMEOUT_MAX)


def clean_text(text: str) -> str | None:
    """Send text to Claude Haiku for cleanup. Returns cleaned text or None on failure."""
    timeout = compute_timeout(text)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": text}],
            system=CLEANUP_PROMPT,
            timeout=timeout,
        )
        return response.content[0].text
    except Exception as e:
        log(f"API error: {e}")
        return None


def handle_clean_hotkey() -> None:
    """Handle Cmd+Ctrl+V: clean the last captured paste."""
    global last_paste_text

    if not lock.acquire(blocking=False):
        return
    try:
        with last_paste_lock:
            text = last_paste_text

        if not text or not text.strip():
            log("Skipped: no captured paste text")
            return
        if len(text) > MAX_INPUT_CHARS:
            log(f"Skipped: text too long ({len(text)} chars > {MAX_INPUT_CHARS})")
            return

        start = time.time()
        timeout = compute_timeout(text)
        log(f"Cleaning {len(text)} chars (timeout {timeout:.1f}s)...")

        cleaned = clean_text(text)

        if cleaned is None:
            log("Failed: no response from API — original text preserved")
            return

        # Undo the original paste
        simulate_keystroke(VK_Z, kCGEventFlagMaskCommand)
        time.sleep(0.15)

        # Paste cleaned text
        set_clipboard(cleaned)
        time.sleep(0.05)
        simulate_keystroke(VK_V, kCGEventFlagMaskCommand)

        elapsed_ms = int((time.time() - start) * 1000)
        log(f"Done ({len(text)} -> {len(cleaned)} chars, {elapsed_ms}ms)")
    except Exception as e:
        log(f"Failed: {e}")
    finally:
        lock.release()


def event_tap_callback(proxy, event_type, event, refcon):
    """CGEventTap callback — intercepts key events to detect Cmd+V and Cmd+Ctrl+V."""
    global last_paste_text

    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    flags = CGEventGetFlags(event)

    if keycode != VK_V:
        return event

    has_cmd = bool(flags & kCGEventFlagMaskCommand)
    has_ctrl = bool(flags & kCGEventFlagMaskControl)

    if has_cmd and has_ctrl:
        # Cmd+Ctrl+V — our cleanup hotkey
        threading.Thread(target=handle_clean_hotkey, daemon=True).start()
        return None  # Suppress the original event

    if has_cmd and not has_ctrl:
        # Regular Cmd+V — capture clipboard at this moment
        clipboard = get_clipboard()
        if clipboard:
            with last_paste_lock:
                last_paste_text = clipboard

    return event


_run_loop_ref = None


def main() -> None:
    global _run_loop_ref

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set")
        sys.exit(1)

    # Create event tap for key down events
    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        0,  # active tap (can modify/suppress events)
        CGEventMaskBit(kCGEventKeyDown),
        event_tap_callback,
        None,
    )

    if tap is None:
        print(
            "Error: Could not create event tap.\n"
            "Grant Accessibility permission in:\n"
            "  System Settings > Privacy & Security > Accessibility\n"
            "Add your terminal app (Terminal, iTerm2, etc.) to the list."
        )
        sys.exit(1)

    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    _run_loop_ref = CFRunLoopGetCurrent()
    CFRunLoopAddSource(_run_loop_ref, source, kCFRunLoopCommonModes)

    def on_sigint(signum, frame):
        log("Shutting down...")
        if _run_loop_ref:
            CFRunLoopStop(_run_loop_ref)

    signal.signal(signal.SIGINT, on_sigint)

    log("Clipboard cleaner started (CGEventTap).")
    log("Every Cmd+V is captured. Press Cmd+Ctrl+V to clean the last paste.")

    CFRunLoopRun()


if __name__ == "__main__":
    main()
