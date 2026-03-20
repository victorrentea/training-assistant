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
4. Strip any markdown fences Claude may have wrapped around the response
5. Normalize detected language to lowercase (to match host.html select values: `java`, `python`, etc.)
6. Use extracted code as the snippet; if `code` is empty, fall back to raw snippet
7. Validate `_MAX_LINES` **after** extraction (the extracted code may have fewer lines than the raw input)
8. If host selected "Auto-detect" (`language: null`), use Claude's detected language
9. If host manually selected a language, keep the host's choice

**Claude prompt:**
```
Extract only the code snippet from the following text.
Remove any markdown formatting, explanations, comments about the code, or surrounding text.
Return ONLY a JSON object with two fields:
- "code": the extracted code (preserve original indentation, no markdown fences)
- "language": the programming language as lowercase identifier (one of: java, python, javascript, typescript, sql, go, csharp, kotlin, bash, or null if unknown)

If the input is already clean code with no surrounding text, return it as-is in the JSON format.
```

**API configuration:**
- Reuse `ANTHROPIC_API_KEY` from `secrets.env` (same pattern as `quiz_core.py`)
- Use synchronous `Anthropic` client (consistent with existing `debate.py` pattern; acceptable since only the host triggers this and sessions tolerate 1-2s blocking)
- Model: `claude-haiku-4-5-20251001` (fast, cheap)
- Max tokens: 4096
- Timeout: 5 seconds (via `httpx.Timeout` on the client)
- Input guard: truncate raw snippet to 10,000 characters before sending to Claude

**Error handling:**
- All failures (missing API key, timeout, network error, malformed JSON, empty `code` field) silently fall back to the raw snippet
- No user-visible error — the feature degrades gracefully

### Frontend (`static/host.html` + `static/host.js`)

**UI additions:**
- Checkbox: "Smart paste (extract code from LLM output)" — checked by default
- Located near the code textarea in the code review section

**JS changes:**
- `startCodeReview()` reads the checkbox value and includes `smart_paste` in the POST body
- Disable the Start button and show "Extracting code..." while the request is in flight (prevents double-click, Claude call adds ~1-2s latency)
- Re-enable button after response (success or failure)

### Dependencies

- `anthropic` package already in `pyproject.toml`
- `ANTHROPIC_API_KEY` already configured in `secrets.env`

## Scope

- Only applies to the code review paste flow
- No changes to participant experience
- No changes to WebSocket protocol
- No new endpoints
