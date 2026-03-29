#!/usr/bin/env python3
"""Clipboard cleanup daemon using Claude Haiku and macOS CGEventTap.

Intercepts every Cmd+V at the system level to capture clipboard contents
(including ephemeral pastes from tools like Wispr Flow).
When the user presses Cmd+Ctrl+V, the last captured paste is cleaned via AI,
the original paste is undone, and the cleaned version is pasted in its place.

Also intercepts Mouse Button 5 (Wispr Flow dictation toggle) to mute/unmute
the "OS Output" loopback device so meeting participants don't hear system audio.
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
import rumps
from pathlib import Path
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
    kCGEventFlagsChanged,
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
_EMOJI_PROMPT_OPTIONAL = (
    "Fix grammar, punctuation, and spelling errors.\n"
    "Remove filler words and false starts from speech-to-text output.\n"
    "Synthesize verbose text into concise form while preserving all meaning.\n"
    "You may add an emoji only if it genuinely fits the context — it's fine to add none.\n"
    "Detect the input language and respond in the same language.\n"
    "Return ONLY the cleaned text, nothing else."
)

_EMOJI_PROMPT_ENRICH = (
    "Fix grammar, punctuation, and spelling errors.\n"
    "Remove filler words and false starts from speech-to-text output.\n"
    "Synthesize verbose text into concise form while preserving all meaning.\n"
    "Enrich the text with emojis: add at least one, typically one per sentence or key idea, occasionally more where it fits naturally.\n"
    "Detect the input language and respond in the same language.\n"
    "Return ONLY the cleaned text, nothing else."
)

CLEANUP_PROMPT_EMOJI = _EMOJI_PROMPT_ENRICH  # default for menu-bar click

# macOS virtual key codes
VK_V = 0x09
VK_Z = 0x06
VK_ESCAPE = 0x35

# Mouse button 5 = button index 4 (0=left, 1=right, 2=middle, 3=button4, 4=button5)
MOUSE_BUTTON_5 = 4

# The loopback device to mute during dictation
DICTATION_MUTE_DEVICE = "\U0001f50aOS Output"  # 🔊OS Output

# --- CoreAudio helpers for per-device mute ---
_ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))


class _AudioPropAddr(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_kScopeGlobal = 1735159650   # 'glob'
_kScopeOutput = 1869968496   # 'outp'
_kElementMain = 0
_kDevices = 1684370979       # 'dev#'
_kName = 1819173229          # 'lnam'
_kVolume = 1986885219        # 'volm'

DICTATION_VOLUME_LOW = 0.01  # ~silent during dictation
DICTATION_MUTE_DELAY = 0.05  # 50ms delay before lowering volume
_mute_device_original_volume: float = 1.0
_dictation_active: bool = False

# Media key type for play/pause (NX_KEYTYPE_PLAY)
_NX_KEYTYPE_PLAY = 16


def _send_media_play_pause() -> None:
    """Simulate pressing the media play/pause key via NSSystemDefined event."""
    for key_down in (True, False):
        flags = 0xa00 if key_down else 0xb00
        data1 = (_NX_KEYTYPE_PLAY << 16) | flags
        event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14,  # NSEventTypeSystemDefined
            (0, 0),
            0,
            0,
            0,
            None,
            8,  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
            data1,
            -1,
        )
        CGEventPost(0, event.CGEvent())


def _find_audio_device_id(name: str) -> int | None:
    """Find an audio output device ID by name."""
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
    """Get the current volume (0.0–1.0) of a specific audio device."""
    addr = _AudioPropAddr(_kVolume, _kScopeOutput, _kElementMain)
    val = ctypes.c_float(0)
    size = ctypes.c_uint32(4)
    if _ca.AudioObjectGetPropertyData(device_id, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(val)) == 0:
        return val.value
    return 1.0


def _set_device_volume(device_id: int, volume: float) -> bool:
    """Set the volume (0.0–1.0) of a specific audio device. Returns True on success."""
    addr = _AudioPropAddr(_kVolume, _kScopeOutput, _kElementMain)
    val = ctypes.c_float(volume)
    return _ca.AudioObjectSetPropertyData(device_id, ctypes.byref(addr), 0, None, 4, ctypes.byref(val)) == 0


client = anthropic.Anthropic(max_retries=0)
lock = threading.Lock()

# Stores the clipboard content captured at the moment of each Cmd+V
last_paste_text: str | None = None
last_paste_lock = threading.Lock()

# Tracks when Ctrl+Opt were pressed together (for emoji hold-duration)
_ctrl_opt_pressed_at: float | None = None


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


def clean_text(text: str, with_emoji: bool = False, emoji_enrich: bool = True) -> str | None:
    """Send text to Claude Haiku for cleanup. Returns cleaned text or None on failure."""
    timeout = compute_timeout(text)
    if with_emoji:
        prompt = _EMOJI_PROMPT_ENRICH if emoji_enrich else _EMOJI_PROMPT_OPTIONAL
    else:
        prompt = CLEANUP_PROMPT
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


def handle_clean_hotkey(with_emoji: bool = False, hold_seconds: float = 0.0) -> None:
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
        emoji_enrich = hold_seconds >= 1.0
        emoji_tag = f" +emoji({'enrich' if emoji_enrich else 'optional'}, held {hold_seconds:.1f}s)" if with_emoji else ""
        log(f"Cleaning {len(text)} chars{emoji_tag} (timeout {timeout:.1f}s)...")

        cleaned = clean_text(text, with_emoji=with_emoji, emoji_enrich=emoji_enrich)

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
        log(f"Done ({len(text)} -> {len(cleaned)} chars, {elapsed_ms}ms):\n  {cleaned[:200]}")
    except Exception as e:
        log(f"Failed: {e}")
    finally:
        lock.release()


def handle_dictation_toggle() -> None:
    """Handle Mouse Button 5: toggle OS Output volume between normal and ~silent.

    Resolves the device ID by name each time because CoreAudio IDs change
    when AudioHijack or Loopback restarts.
    """
    global _mute_device_original_volume, _dictation_active
    if _dictation_active:
        _restore_dictation_volume()
    else:
        device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
        if device_id is None:
            log(f"WARNING: Device '{DICTATION_MUTE_DEVICE}' not found — skipping")
            return
        current_vol = _get_device_volume(device_id)
        _mute_device_original_volume = current_vol
        time.sleep(DICTATION_MUTE_DELAY)
        _set_device_volume(device_id, DICTATION_VOLUME_LOW)
        _dictation_active = True
        log(f"\U0001f7e2 Dictation: \U0001f507 OS Output ({current_vol:.0%}\u2192{DICTATION_VOLUME_LOW:.0%})")


def _restore_dictation_volume() -> None:
    """Restore OS Output volume after dictation ends."""
    global _dictation_active
    if not _dictation_active:
        return
    device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
    if device_id is None:
        log(f"WARNING: Device '{DICTATION_MUTE_DEVICE}' not found — skipping")
        _dictation_active = False
        return
    _set_device_volume(device_id, _mute_device_original_volume)
    _dictation_active = False
    log(f"\U0001f534 Dictation: \U0001f50a OS Output ({_mute_device_original_volume:.0%})")


def event_tap_callback(proxy, event_type, event, refcon):
    """CGEventTap callback — intercepts key + mouse events."""
    global last_paste_text, _ctrl_opt_pressed_at

    # macOS disables the tap if the callback is too slow — re-enable it
    if event_type == kCGEventTapDisabledByTimeout:
        log("⚠️ Event tap disabled by timeout — re-enabling")
        if _tap_ref is not None:
            CGEventTapEnable(_tap_ref, True)
        return event

    if event_type == kCGEventOtherMouseDown:
        button = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
        if button == MOUSE_BUTTON_5:
            threading.Thread(target=handle_dictation_toggle, daemon=True).start()
        return event

    # Track Ctrl+Opt hold start/end via flags-changed events
    if event_type == kCGEventFlagsChanged:
        flags = CGEventGetFlags(event)
        both_held = bool(flags & kCGEventFlagMaskControl) and bool(flags & kCGEventFlagMaskAlternate)
        if both_held and _ctrl_opt_pressed_at is None:
            _ctrl_opt_pressed_at = time.time()
        elif not both_held and _ctrl_opt_pressed_at is not None:
            _ctrl_opt_pressed_at = None
        return event

    # Key events
    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    flags = CGEventGetFlags(event)

    # Escape while dictating → restore volume
    if keycode == VK_ESCAPE and _dictation_active:
        threading.Thread(target=_restore_dictation_volume, daemon=True).start()
        return event

    if keycode != VK_V:
        return event

    has_cmd = bool(flags & kCGEventFlagMaskCommand)
    has_ctrl = bool(flags & kCGEventFlagMaskControl)
    has_opt = bool(flags & kCGEventFlagMaskAlternate)

    if has_cmd and has_ctrl:
        # Cmd+Ctrl+V — cleanup; Cmd+Ctrl+Opt+V — cleanup with emojis
        hold = (time.time() - _ctrl_opt_pressed_at) if (has_opt and _ctrl_opt_pressed_at) else 0.0
        threading.Thread(target=handle_clean_hotkey, args=(has_opt, hold), daemon=True).start()
        return None  # Suppress the original event

    if has_cmd and not has_ctrl:
        # Regular Cmd+V — capture clipboard at this moment
        clipboard = get_clipboard()
        if clipboard:
            with last_paste_lock:
                last_paste_text = clipboard

    return event


_tap_ref = None
_tap_run_loop_ref = None


def _run_event_tap() -> None:
    """Run the CGEventTap on a background thread with its own CFRunLoop."""
    global _tap_ref, _tap_run_loop_ref

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        0,  # active tap (can modify/suppress events)
        CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventOtherMouseDown),
        event_tap_callback,
        None,
    )

    _tap_ref = tap
    if tap is None:
        print(
            "Error: Could not create event tap.\n"
            "Grant Accessibility permission in:\n"
            "  System Settings > Privacy & Security > Accessibility\n"
            "Add your terminal app (Terminal, iTerm2, etc.) to the list."
        )
        os._exit(1)

    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    _tap_run_loop_ref = CFRunLoopGetCurrent()
    CFRunLoopAddSource(_tap_run_loop_ref, source, kCFRunLoopCommonModes)
    CFRunLoopRun()


class CleanerApp(rumps.App):
    def __init__(self):
        menu = [
            rumps.MenuItem("Clean Repaste   ⌘⌃V", callback=self.on_clean),
            rumps.MenuItem("Clean Repaste + Emoji   ⌘⌃⌥V", callback=self.on_clean_emoji),
            None,  # separator
            rumps.MenuItem("Mouse 5: pause music + mute OS Output", callback=None),
        ]
        super().__init__("✂", menu=menu)
        self.menu["Mouse 5: pause music + mute OS Output"].enabled = False

    def on_clean(self, _):
        threading.Thread(target=handle_clean_hotkey, args=(False,), daemon=True).start()

    def on_clean_emoji(self, _):
        threading.Thread(target=handle_clean_hotkey, args=(True,), daemon=True).start()


def main() -> None:
    # Load secrets from ~/.training-assistants-secrets.env
    secrets_path = Path.home() / ".training-assistants-secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()
    api_key = os.environ.get("WISPR_CLEANUP_ANTHROPIC_API_KEY")
    if not api_key:
        print(f"Error: WISPR_CLEANUP_ANTHROPIC_API_KEY not set in {secrets_path}")
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    # Verify the loopback device exists at startup (ID resolved fresh each toggle)
    device_id = _find_audio_device_id(DICTATION_MUTE_DEVICE)
    if device_id:
        log(f"Dictation mute device: {DICTATION_MUTE_DEVICE} (ID {device_id})")
    else:
        log(f"WARNING: Device '{DICTATION_MUTE_DEVICE}' not found — dictation mute may not work")

    log("Clipboard cleaner started (CGEventTap).")
    log("Every Cmd+V is captured. Press Cmd+Ctrl+V to clean the last paste.")
    log("Hold Option (Cmd+Ctrl+Opt+V) to clean with contextual emojis.")
    if device_id:
        log(f"Mouse Button 5 toggles volume on '{DICTATION_MUTE_DEVICE}'.")

    # Signal handlers: stop event tap run loop + quit rumps
    def on_shutdown(signum, frame):
        log("Shutting down...")
        if _dictation_active:
            _restore_dictation_volume()
        if _tap_run_loop_ref:
            CFRunLoopStop(_tap_run_loop_ref)
        rumps.quit_application()

    signal.signal(signal.SIGINT, on_shutdown)
    signal.signal(signal.SIGTERM, on_shutdown)

    # Start event tap in background thread; rumps owns the main thread
    threading.Thread(target=_run_event_tap, daemon=True).start()
    CleanerApp().run()


if __name__ == "__main__":
    main()
