#!/usr/bin/env python3
"""Wispr Addons — macOS menu bar app.

Wraps the clipboard cleanup daemon (CGEventTap) in a menu bar app using rumps.
The event tap runs on a background thread; the main thread runs the menu bar UI.
"""

import ctypes
import ctypes.util
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import anthropic
import objc
import AppKit
import rumps
import Quartz
from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventPost,
    CGEventTapCreate,
    CGEventTapEnable,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGEventKeyDown,
    kCGEventOtherMouseDown,
    kCGEventTapDisabledByTimeout,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGMouseEventButtonNumber,
)
from AppKit import NSEvent

# --- Configuration ---
MODEL = "claude-haiku-4-5-20251001"
TIMEOUT_BASE = 2
TIMEOUT_PER_1K = 1.5
TIMEOUT_MAX = 15
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

VK_V = 0x09
VK_Z = 0x06
VK_ESCAPE = 0x35
MOUSE_BUTTON_5 = 4
DICTATION_MUTE_DEVICE = "\U0001f50aOS Output"
DICTATION_VOLUME_LOW = 0.01
DICTATION_MUTE_DELAY = 0.05

# --- CoreAudio helpers ---
_ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))


class _AudioPropAddr(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_kScopeGlobal = 1735159650
_kScopeOutput = 1869968496
_kElementMain = 0
_kDevices = 1684370979
_kName = 1819173229
_kVolume = 1986885219
_NX_KEYTYPE_PLAY = 16


def _find_audio_device_id(name: str) -> int | None:
    addr = _AudioPropAddr(_kDevices, _kScopeGlobal, _kElementMain)
    size = ctypes.c_uint32(0)
    _ca.AudioObjectGetPropertyDataSize(1, ctypes.byref(addr), 0, None, ctypes.byref(size))
    n = size.value // 4
    ids = (ctypes.c_uint32 * n)()
    _ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(size), ids)
    for i in range(n):
        dev_id = ids[i]
        na = _AudioPropAddr(_kName, _kScopeGlobal, _kElementMain)
        ref = ctypes.c_void_p()
        ns = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        if _ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(na), 0, None, ctypes.byref(ns), ctypes.byref(ref)) != 0:
            continue
        if str(objc.objc_object(c_void_p=ref)) == name:
            return dev_id
    return None


def _get_device_volume(device_id: int) -> float:
    addr = _AudioPropAddr(_kVolume, _kScopeOutput, _kElementMain)
    val = ctypes.c_float(0)
    size = ctypes.c_uint32(4)
    if _ca.AudioObjectGetPropertyData(device_id, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(val)) == 0:
        return val.value
    return 1.0


def _set_device_volume(device_id: int, volume: float) -> bool:
    addr = _AudioPropAddr(_kVolume, _kScopeOutput, _kElementMain)
    val = ctypes.c_float(volume)
    return _ca.AudioObjectSetPropertyData(device_id, ctypes.byref(addr), 0, None, 4, ctypes.byref(val)) == 0


# --- Shared state ---
_client: anthropic.Anthropic | None = None
_clean_lock = threading.Lock()
_last_paste_text: str | None = None
_last_paste_lock = threading.Lock()
_mute_device_original_volume: float = 1.0
_dictation_active: bool = False
_tap_ref = None
_tap_run_loop_ref = None
_log_buffer: deque[str] = deque(maxlen=50)
_app_ref: "WisprAddonsApp | None" = None


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    _log_buffer.append(line)


# --- Clipboard & keystroke helpers ---
def get_clipboard() -> str:
    try:
        return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=1).stdout
    except Exception:
        return ""


def set_clipboard(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=1)
    except Exception as e:
        log(f"pbcopy failed: {e}")


def simulate_keystroke(keycode: int, flags: int = 0) -> None:
    if keycode == VK_V and flags == kCGEventFlagMaskCommand:
        subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], timeout=2)
    elif keycode == VK_Z and flags == kCGEventFlagMaskCommand:
        subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "z" using command down'], timeout=2)


def compute_timeout(text: str) -> float:
    return min(TIMEOUT_BASE + (len(text) / 1000) * TIMEOUT_PER_1K, TIMEOUT_MAX)


def play_sound() -> None:
    subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- Core handlers ---
def clean_text(text: str, with_emoji: bool = False) -> str | None:
    timeout = compute_timeout(text)
    prompt = CLEANUP_PROMPT_EMOJI if with_emoji else CLEANUP_PROMPT
    try:
        response = _client.messages.create(
            model=MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": text}],
            system=prompt, timeout=timeout,
        )
        return response.content[0].text
    except Exception as e:
        log(f"API error: {e}")
        return None


def handle_clean_hotkey(with_emoji: bool = False) -> None:
    global _last_paste_text
    if not _clean_lock.acquire(blocking=False):
        return
    try:
        play_sound()
        with _last_paste_lock:
            text = _last_paste_text
        if not text or not text.strip():
            log("Skipped: no captured paste text")
            return
        if len(text) > MAX_INPUT_CHARS:
            log(f"Skipped: text too long ({len(text)} chars > {MAX_INPUT_CHARS})")
            return

        start = time.time()
        emoji_tag = " +emoji" if with_emoji else ""
        log(f"Cleaning {len(text)} chars{emoji_tag}...")
        if _app_ref:
            _app_ref.title = "\U0001f9f9"  # broom — cleaning in progress

        cleaned = clean_text(text, with_emoji=with_emoji)
        if cleaned is None:
            log("Failed: no response from API")
            if _app_ref:
                _app_ref.title = "\U0001f9d1\u200d\U0001f4bb"
            return

        simulate_keystroke(VK_Z, kCGEventFlagMaskCommand)
        time.sleep(0.15)
        set_clipboard(cleaned)
        time.sleep(0.05)
        simulate_keystroke(VK_V, kCGEventFlagMaskCommand)

        elapsed_ms = int((time.time() - start) * 1000)
        log(f"Done ({len(text)}\u2192{len(cleaned)} chars, {elapsed_ms}ms):\n  {cleaned[:200]}")
        if _app_ref:
            _app_ref.title = "\U0001f9d1\u200d\U0001f4bb"
    except Exception as e:
        log(f"Failed: {e}")
    finally:
        _clean_lock.release()


def handle_dictation_toggle() -> None:
    global _mute_device_original_volume, _dictation_active
    if _dictation_active:
        _restore_dictation_volume()
    else:
        device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
        if device_id is None:
            log(f"WARNING: Device '{DICTATION_MUTE_DEVICE}' not found")
            return
        current_vol = _get_device_volume(device_id)
        _mute_device_original_volume = current_vol
        time.sleep(DICTATION_MUTE_DELAY)
        _set_device_volume(device_id, DICTATION_VOLUME_LOW)
        _dictation_active = True
        log(f"\U0001f7e2 Dictation: \U0001f507 OS Output ({current_vol:.0%}\u2192{DICTATION_VOLUME_LOW:.0%})")
        if _app_ref:
            _app_ref.title = "\U0001f3a4"  # microphone — dictating


def _restore_dictation_volume() -> None:
    global _dictation_active
    if not _dictation_active:
        return
    device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
    if device_id is None:
        log(f"WARNING: Device '{DICTATION_MUTE_DEVICE}' not found")
        _dictation_active = False
        return
    _set_device_volume(device_id, _mute_device_original_volume)
    _dictation_active = False
    log(f"\U0001f534 Dictation: \U0001f50a OS Output ({_mute_device_original_volume:.0%})")
    if _app_ref:
        _app_ref.title = "\U0001f9d1\u200d\U0001f4bb"


# --- Event tap callback ---
def event_tap_callback(proxy, event_type, event, refcon):
    global _last_paste_text

    if event_type == kCGEventTapDisabledByTimeout:
        log("\u26a0\ufe0f Event tap re-enabled after timeout")
        if _tap_ref is not None:
            CGEventTapEnable(_tap_ref, True)
        return event

    if event_type == kCGEventOtherMouseDown:
        button = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
        if button == MOUSE_BUTTON_5:
            threading.Thread(target=handle_dictation_toggle, daemon=True).start()
        return event

    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    flags = CGEventGetFlags(event)

    if keycode == VK_ESCAPE and _dictation_active:
        threading.Thread(target=_restore_dictation_volume, daemon=True).start()
        return event

    if keycode != VK_V:
        return event

    has_cmd = bool(flags & kCGEventFlagMaskCommand)
    has_ctrl = bool(flags & kCGEventFlagMaskControl)
    has_opt = bool(flags & kCGEventFlagMaskAlternate)

    if has_cmd and has_ctrl:
        threading.Thread(target=handle_clean_hotkey, args=(has_opt,), daemon=True).start()
        return None

    if has_cmd and not has_ctrl:
        clipboard = get_clipboard()
        if clipboard:
            with _last_paste_lock:
                _last_paste_text = clipboard

    return event


# --- Event tap thread ---
def _run_event_tap():
    global _tap_ref, _tap_run_loop_ref

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        0,
        CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventOtherMouseDown),
        event_tap_callback,
        None,
    )

    _tap_ref = tap
    if tap is None:
        log("ERROR: Could not create event tap — check Accessibility permissions")
        return

    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    _tap_run_loop_ref = CFRunLoopGetCurrent()
    CFRunLoopAddSource(_tap_run_loop_ref, source, kCFRunLoopCommonModes)

    device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
    if device_id:
        log(f"Dictation device: {DICTATION_MUTE_DEVICE} (ID {device_id})")
    else:
        log(f"WARNING: '{DICTATION_MUTE_DEVICE}' not found")

    log("Event tap active")
    CFRunLoopRun()
    log("Event tap stopped")


# --- Menu bar app ---
class WisprAddonsApp(rumps.App):
    def __init__(self):
        super().__init__(
            "\U0001f9d1\u200d\U0001f4bb",  # 🧑‍💻 idle state
            icon=None,
            template=False,
            quit_button=None,
        )
        self.menu = [
            rumps.MenuItem("Hotkeys:", callback=None),
            rumps.MenuItem("  \u2318\u2303V — Clean paste", callback=None),
            rumps.MenuItem("  \u2318\u2303\u2325V — Clean + emoji", callback=None),
            rumps.MenuItem("  Mouse 5 — Dictation mute", callback=None),
            None,  # separator
            rumps.MenuItem("Show Log", callback=self.show_log),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

    def show_log(self, _):
        log_text = "\n".join(_log_buffer) if _log_buffer else "(no log entries yet)"
        rumps.alert(title="Wispr Addons Log", message=log_text)

    def quit_app(self, _):
        if _dictation_active:
            _restore_dictation_volume()
        if _tap_run_loop_ref:
            CFRunLoopStop(_tap_run_loop_ref)
        rumps.quit_application()


def main():
    global _client, _app_ref

    # Load API key
    secrets_path = Path.home() / ".training-assistants-secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        rumps.alert("Wispr Addons", f"ANTHROPIC_API_KEY not set.\nAdd it to:\n{secrets_path}")
        sys.exit(1)

    _client = anthropic.Anthropic(max_retries=0)

    # Start event tap on background thread
    tap_thread = threading.Thread(target=_run_event_tap, daemon=True)
    tap_thread.start()

    log("Wispr Addons started")

    # Hide from Cmd+Tab (menu bar only, no dock icon)
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    # Run menu bar app on main thread
    _app_ref = WisprAddonsApp()
    _app_ref.run()


if __name__ == "__main__":
    main()
