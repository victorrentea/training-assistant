# Clean Clipboard

A macOS daemon that cleans speech-to-text clipboard content via Claude Haiku. Press **Cmd+Ctrl+V** after pasting to replace the pasted text with a cleaned version (grammar fixes, filler removal, concise synthesis).

## Prerequisites

- Python 3.12
- `ANTHROPIC_API_KEY` in environment or in `~/.training-assistants-secrets.env`
- macOS Accessibility permission for your terminal app

## Install

```bash
pip3 install -r requirements.txt
```

## macOS Permission

Grant Accessibility access to your terminal app:
**System Settings > Privacy & Security > Accessibility** > add Terminal.app / iTerm2 / Warp

## Run

```bash
ANTHROPIC_API_KEY=sk-... python3 clean.py
```

Or with key in `~/.training-assistants-secrets.env` (or already exported):

```bash
python3 clean.py
```

## Usage

1. Paste text normally (Cmd+V or via Whispr Flow)
2. Immediately press **Cmd+Ctrl+V**
3. The daemon undoes the paste, cleans the text via AI, and re-pastes the cleaned version

Timeout scales with text length: ~2s for short text, up to 15s for very long dictations. If the AI call fails or times out, the original text stays untouched.

## Configuration

Edit constants at the top of `clean.py`:

| Constant | Default | Description |
|---|---|---|
| `MODEL` | `claude-haiku-4-5-20251001` | Claude model for cleanup |
| `TIMEOUT_BASE` | `2` | Base timeout in seconds (for short text) |
| `TIMEOUT_PER_1K` | `1.5` | Extra seconds per 1000 characters |
| `TIMEOUT_MAX` | `15` | Hard cap on timeout |
| `MAX_INPUT_CHARS` | `5000` | Skip cleanup for text longer than this |

## Dictation Mode (Mouse Button 5)

When dictation starts (Mouse Button 5 / Wispr Flow toggle):
- **Pauses** media playback via macOS media key simulation
- **Lowers** the "OS Output" loopback device volume to ~silent

When dictation stops (Mouse Button 5 again, or Escape):
- **Resumes** media playback
- **Restores** the original volume level

Double-click Mouse Button 3 (wheel click):
- **Repastes** the last text captured from Wispr Flow/Cmd+V at the current cursor position

This ensures meeting/stream audio doesn't leak into dictation, even for apps that ignore volume changes.

## Stop

Press **Ctrl+C** in the terminal.
