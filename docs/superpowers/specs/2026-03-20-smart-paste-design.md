# Smart Paste: Auto-Extract Code from LLM Responses

**Issue:** gh#23
**Date:** 2026-03-20
**Status:** Approved

## Problem

When the host pastes code from LLM responses (ChatGPT, Claude, etc.) into the code review activity, the paste often includes markdown formatting, explanations, and surrounding text. The host must manually clean this up before starting the activity.

## Solution

Integrate a Claude API call into the existing `POST /api/codereview` endpoint to automatically extract clean code and detect the programming language from pasted text.

## Design

### Backend (`routers/codereview.py`)

**Model change:**
- Add `smart_paste: bool = True` to `CodeReviewCreate`

**Flow when `smart_paste` is true:**
1. Call Claude API (Haiku model for speed/cost) with the raw snippet
2. Prompt asks Claude to extract only the code and detect the language
3. Parse structured JSON response: `{"code": "...", "language": "..."}`
4. Use extracted code as the snippet
5. If host selected "Auto-detect" for language, use Claude's detected language
6. If host manually selected a language, keep the host's choice

**Claude prompt:**
```
Extract only the code snippet from the following text.
Remove any markdown formatting, explanations, comments about the code, or surrounding text.
Return ONLY a JSON object with two fields:
- "code": the extracted code (preserve original indentation)
- "language": the programming language (one of: Java, Python, JavaScript, TypeScript, SQL, Go, C#, Kotlin, Bash, or null if unknown)

If the input is already clean code with no surrounding text, return it as-is.
```

**API configuration:**
- Reuse `ANTHROPIC_API_KEY` from `secrets.env` (same pattern as `quiz_core.py`)
- Model: `claude-haiku-4-5-20251001` (fast, cheap)
- Max tokens: 4096
- Timeout: 5 seconds

**Error handling:**
- All failures (missing API key, timeout, network error, malformed JSON response) silently fall back to the raw snippet
- No user-visible error — the feature degrades gracefully

### Frontend (`static/host.html` + `static/host.js`)

**UI additions:**
- Checkbox: "Smart paste (extract code from LLM output)" — checked by default
- Located near the code textarea in the code review section

**JS changes:**
- `startCodeReview()` reads the checkbox value and includes `smart_paste` in the POST body
- Add a loading indicator ("Extracting code...") on the Start button while the request is in flight (the Claude call adds ~1-2s latency)

### Dependencies

- `anthropic` package already in `pyproject.toml`
- `ANTHROPIC_API_KEY` already configured in `secrets.env`

## Scope

- Only applies to the code review paste flow
- No changes to participant experience
- No changes to WebSocket protocol
- No new endpoints
