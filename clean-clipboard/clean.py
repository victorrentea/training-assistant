#!/usr/bin/env python3
"""Clipboard cleanup daemon using Claude Haiku and macOS CGEventTap.

Intercepts every Cmd+V at the system level to capture clipboard contents
(including ephemeral pastes from tools like Wispr Flow).
When the user presses Cmd+Ctrl+V, the last captured paste is cleaned via AI,
the original paste is undone, and the cleaned version is pasted in its place.

Also intercepts Mouse Button 4 (Wispr Flow dictation toggle) to auto-mute
system output while recording. Uses Elgato Wave XLR mic running state as
ground truth to avoid toggle sync issues.
"""

import ctypes
import ctypes.util
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

import anthropic
import objc
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
    kCGEventOtherMouseDown,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGMouseEventButtonNumber,
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
CLEANUP_PROMPT_EMOJI = (
    "Fix grammar, punctuation, and spelling errors.\n"
    "Remove filler words and false starts from speech-to-text output.\n"
    "Synthesize verbose text into concise form while preserving all meaning.\n"
    "Insert emojis in contextually appropriate positions throughout the text.\n"
    "Detect the input language and respond in the same language.\n"
    "Return ONLY the cleaned text, nothing else."
)

# macOS virtual key codes
VK_V = 0x09
VK_Z = 0x06

# Mouse button 4 = button index 3 (0=left, 1=right, 2=middle, 3=button4)
MOUSE_BUTTON_4 = 3

# Dictation mute: mic device to check and delay before muting
DICTATION_MIC_NAME = "Elgato Wave XLR"
DICTATION_MUTE_DELAY_MS = 50

# --- CoreAudio helpers for mic running detection ---
_ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_kAudioObjectSystemObject = 1
_kAudioObjectPropertyScopeGlobal = 1735159650   # 'glob'
_kAudioObjectPropertyScopeInput = 1768845428     # 'inpt'
_kAudioObjectPropertyElementMain = 0
_kAudioHardwarePropertyDevices = 1684370979      # 'dev#'
_kAudioObjectPropertyName = 1819173229           # 'lnam'
_kAudioDevicePropertyDeviceIsRunningSomewhere = 1769174643  # 'goin'
_kAudioDevicePropertyStreams = 1937009955         # 'stm#'


def _find_audio_device_id(name: str) -> int | None:
    """Find an audio device ID by name. Returns None if not found."""
    addr = _AudioObjectPropertyAddress(
        _kAudioHardwarePropertyDevices, _kAudioObjectPropertyScopeGlobal, _kAudioObjectPropertyElementMain
    )
    size = ctypes.c_uint32(0)
    _ca.AudioObjectGetPropertyDataSize(
        _kAudioObjectSystemObject, ctypes.byref(addr), 0, None, ctypes.byref(size)
    )
    n = size.value // 4
    device_ids = (ctypes.c_uint32 * n)()
    _ca.AudioObjectGetPropertyData(
        _kAudioObjectSystemObject, ctypes.byref(addr), 0, None, ctypes.byref(size), device_ids
    )
    for i in range(n):
        dev_id = device_ids[i]
        name_addr = _AudioObjectPropertyAddress(
            _kAudioObjectPropertyName, _kAudioObjectPropertyScopeGlobal, _kAudioObjectPropertyElementMain
        )
        name_ref = ctypes.c_void_p()
        name_size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        if _ca.AudioObjectGetPropertyData(
            dev_id, ctypes.byref(name_addr), 0, None, ctypes.byref(name_size), ctypes.byref(name_ref)
        ) != 0:
            continue
        ns_str = objc.objc_object(c_void_p=name_ref)
        if str(ns_str) == name:
            # Verify it has input streams
            in_addr = _AudioObjectPropertyAddress(
                _kAudioDevicePropertyStreams, _kAudioObjectPropertyScopeInput, _kAudioObjectPropertyElementMain
            )
            in_size = ctypes.c_uint32(0)
            if _ca.AudioObjectGetPropertyDataSize(
                dev_id, ctypes.byref(in_addr), 0, None, ctypes.byref(in_size)
            ) == 0 and in_size.value > 0:
                return dev_id
    return None


def is_mic_running(device_id: int) -> bool:
    """Check if an audio input device is currently running (has active streams)."""
    addr = _AudioObjectPropertyAddress(
        _kAudioDevicePropertyDeviceIsRunningSomewhere, _kAudioObjectPropertyScopeGlobal, _kAudioObjectPropertyElementMain
    )
    running = ctypes.c_uint32(0)
    size = ctypes.c_uint32(4)
    if _ca.AudioObjectGetPropertyData(
        device_id, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(running)
    ) == 0:
        return running.value != 0
    return False


def set_system_mute(mute: bool) -> None:
    """Mute or unmute macOS system audio output."""
    flag = "with" if mute else "without"
    subprocess.run(
        ["osascript", "-e", f"set volume {flag} output muted"],
        timeout=2,
        capture_output=True,
    )


# Will be resolved at startup
_dictation_mic_id: int | None = None

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


def play_sound() -> None:
    """Play the macOS system sound to confirm hotkey was received."""
    subprocess.Popen(
        ["afplay", "/System/Library/Sounds/Tink.aiff"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def clean_text(text: str, with_emoji: bool = False) -> str | None:
    """Send text to Claude Haiku for cleanup. Returns cleaned text or None on failure."""
    timeout = compute_timeout(text)
    prompt = CLEANUP_PROMPT_EMOJI if with_emoji else CLEANUP_PROMPT
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": text}],
            system=prompt,
            timeout=timeout,
        )
        return response.content[0].text
    except Exception as e:
        log(f"API error: {e}")
        return None


def handle_clean_hotkey(with_emoji: bool = False) -> None:
    """Handle Cmd+Ctrl+V: clean the last captured paste."""
    global last_paste_text

    if not lock.acquire(blocking=False):
        return
    try:
        play_sound()

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
        emoji_tag = " +emoji" if with_emoji else ""
        log(f"Cleaning {len(text)} chars{emoji_tag} (timeout {timeout:.1f}s)...")

        cleaned = clean_text(text, with_emoji=with_emoji)

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


def handle_dictation_mute() -> None:
    """Handle Mouse Button 4: wait 50ms, check mic state, mute/unmute accordingly."""
    if _dictation_mic_id is None:
        return

    time.sleep(DICTATION_MUTE_DELAY_MS / 1000)

    if is_mic_running(_dictation_mic_id):
        log("Dictation started — muting system output")
        set_system_mute(True)
    else:
        log("Dictation stopped — unmuting system output")
        set_system_mute(False)


def event_tap_callback(proxy, event_type, event, refcon):
    """CGEventTap callback — intercepts key + mouse events."""
    global last_paste_text

    if event_type == kCGEventOtherMouseDown:
        button = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
        if button == MOUSE_BUTTON_4:
            threading.Thread(target=handle_dictation_mute, daemon=True).start()
        return event

    # Key events — only care about V key
    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    flags = CGEventGetFlags(event)

    if keycode != VK_V:
        return event

    has_cmd = bool(flags & kCGEventFlagMaskCommand)
    has_ctrl = bool(flags & kCGEventFlagMaskControl)
    has_opt = bool(flags & kCGEventFlagMaskAlternate)

    if has_cmd and has_ctrl:
        # Cmd+Ctrl+V — cleanup; Cmd+Ctrl+Opt+V — cleanup with emojis
        threading.Thread(target=handle_clean_hotkey, args=(has_opt,), daemon=True).start()
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
    global _run_loop_ref, _dictation_mic_id

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set")
        sys.exit(1)

    # Resolve dictation mic device
    _dictation_mic_id = _find_audio_device_id(DICTATION_MIC_NAME)
    if _dictation_mic_id:
        log(f"Dictation mic found: {DICTATION_MIC_NAME} (ID {_dictation_mic_id})")
    else:
        log(f"WARNING: Dictation mic '{DICTATION_MIC_NAME}' not found — mute on dictation disabled")

    # Create event tap for key down + mouse button events
    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        0,  # active tap (can modify/suppress events)
        CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventOtherMouseDown),
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
    log("Hold Option (Cmd+Ctrl+Opt+V) to clean with contextual emojis.")
    if _dictation_mic_id:
        log("Mouse Button 4 toggles system mute (synced to mic state).")

    CFRunLoopRun()


if __name__ == "__main__":
    main()
