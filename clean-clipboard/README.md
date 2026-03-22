# Clean Clipboard

A macOS daemon that cleans speech-to-text clipboard content via Claude Haiku. Press **Cmd+Ctrl+V** after pasting to replace the pasted text with a cleaned version (grammar fixes, filler removal, concise synthesis).

## Prerequisites

- Python 3.12
- `ANTHROPIC_API_KEY` environment variable set
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

Or if the key is already in your environment:

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

## Stop

Press **Ctrl+C** in the terminal.
