# Smart Paste Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-extract clean code from LLM-formatted pastes in the code review activity using Claude API.

**Architecture:** Add a `smart_paste` flag to the existing `POST /api/codereview` endpoint. When enabled, call Claude Haiku to extract code and detect language before storing. Silent fallback to raw paste on any error.

**Tech Stack:** Python/FastAPI (backend), Anthropic SDK (Claude Haiku), vanilla JS (frontend checkbox + loading state)

**Spec:** `docs/superpowers/specs/2026-03-20-smart-paste-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `routers/codereview.py` | Modify | Add `smart_paste` field, Claude API extraction logic |
| `static/host.html` | Modify | Add "Smart paste" checkbox |
| `static/host.js` | Modify | Send `smart_paste` flag, disable button during request |

---

### Task 1: Add smart paste extraction to backend

**Files:**
- Modify: `routers/codereview.py:17-49`

- [ ] **Step 1: Add `smart_paste` field to `CodeReviewCreate` model**

In `routers/codereview.py`, add the field to the Pydantic model:

```python
class CodeReviewCreate(BaseModel):
    snippet: str
    language: str | None = None
    smart_paste: bool = True
```

- [ ] **Step 2: Add the `_extract_code_with_ai` helper function**

Add `import json` and `import os` at the **top** of `routers/codereview.py` alongside the existing imports. Then add this function above `create_codereview`:

```python
import json
import os

_EXTRACT_PROMPT = """Extract only the code snippet from the following text.
Remove any markdown formatting, explanations, comments about the code, or surrounding text.
Return ONLY a JSON object with two fields:
- "code": the extracted code (preserve original indentation, no markdown fences)
- "language": the programming language as lowercase identifier (one of: java, python, javascript, typescript, sql, go, csharp, kotlin, bash, or null if unknown)

If the input is already clean code with no surrounding text, return it as-is in the JSON format."""

_SMART_PASTE_INPUT_LIMIT = 10000


def _extract_code_with_ai(raw_snippet: str) -> tuple[str, str | None] | None:
    """Call Claude Haiku to extract code from LLM output.
    Returns (code, language) or None on any failure."""
    try:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        truncated = raw_snippet[:_SMART_PASTE_INPUT_LIMIT]
        client = Anthropic(api_key=api_key, timeout=5.0)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": f"{_EXTRACT_PROMPT}\n\n---\n\n{truncated}"}],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if Claude wrapped the JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:text.rfind("```")]
        text = text.strip()

        result = json.loads(text)
        code = result.get("code", "").strip()
        if not code:
            return None
        language = result.get("language")
        if isinstance(language, str):
            language = language.lower()
        logger.info("Smart paste extracted %d lines, language=%s", len(code.splitlines()), language)
        return (code, language)
    except Exception:
        logger.debug("Smart paste extraction failed", exc_info=True)
        return None
```

- [ ] **Step 3: Wire extraction into `create_codereview`**

Modify the `create_codereview` function to call the extractor before validation:

```python
@router.post("/api/codereview", dependencies=[Depends(require_host_auth)])
async def create_codereview(body: CodeReviewCreate):
    snippet = body.snippet.strip()
    if not snippet:
        raise HTTPException(400, "Snippet cannot be empty")

    detected_language = None
    if body.smart_paste:
        result = _extract_code_with_ai(snippet)
        if result:
            snippet, detected_language = result

    lines = snippet.splitlines()
    if len(lines) > _MAX_LINES:
        raise HTTPException(400, f"Snippet cannot exceed {_MAX_LINES} lines")
    if state.current_activity not in (ActivityType.NONE, ActivityType.CODEREVIEW):
        raise HTTPException(409, "Another activity is already active")

    state.codereview_snippet = snippet
    # Use detected language only if host chose "Auto-detect" (null)
    state.codereview_language = body.language if body.language else detected_language
    state.codereview_phase = "selecting"
    state.codereview_selections = {}
    state.codereview_confirmed = set()
    state.current_activity = ActivityType.CODEREVIEW

    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 4: Verify the server starts without errors**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dar-es-salaam && python3 -c "from routers.codereview import router; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add routers/codereview.py
git commit -m "feat: add smart paste code extraction via Claude API (gh#23)"
```

---

### Task 2: Add smart paste checkbox and loading state to host UI

**Files:**
- Modify: `static/host.html:128-159`
- Modify: `static/host.js:1385-1395`

- [ ] **Step 1: Add the checkbox to host.html**

In `static/host.html`, add a checkbox row **after line 143** (the closing `</div>` of the language select row), before the textarea on line 144:

```html
        <label style="display:flex; align-items:center; gap:6px; margin-bottom:8px; font-size:.9rem; cursor:pointer;">
          <input type="checkbox" id="codereview-smart-paste" checked>
          Smart paste (extract code from LLM output)
        </label>
```

- [ ] **Step 2: Update `startCodeReview()` in host.js**

Replace the existing `startCodeReview` function in `static/host.js` (lines 1385-1395):

```javascript
  async function startCodeReview() {
    const snippet = document.getElementById('codereview-snippet').value;
    const langSelect = document.getElementById('codereview-language');
    const language = langSelect.value || null;
    const smartPaste = document.getElementById('codereview-smart-paste').checked;
    if (!snippet.trim()) return alert('Please paste a code snippet');

    const btn = document.querySelector('#codereview-create .btn-success');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = smartPaste ? 'Extracting code...' : 'Starting...';

    try {
      await fetch('/api/codereview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snippet, language, smart_paste: smartPaste }),
      });
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
```

- [ ] **Step 3: Verify the UI renders correctly**

Open `http://localhost:8000/host` in a browser, navigate to the Code Review tab.
Expected: checkbox "Smart paste (extract code from LLM output)" is visible and checked by default, above the textarea.

- [ ] **Step 4: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat: add smart paste checkbox and loading state to host UI (gh#23)"
```

---

### Task 3: Manual end-to-end test

- [ ] **Step 1: Start the server**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dar-es-salaam && python3 -m uvicorn main:app --reload --port 8000`

- [ ] **Step 2: Test with LLM-formatted paste (smart paste ON)**

Open `http://localhost:8000/host`, go to Code Review tab. Paste this text into the textarea:

```
Here's a simple Java method that has some code smells:

```java
public List<String> getActiveUserEmails(List<User> users) {
    List<String> emails = new ArrayList<>();
    for (int i = 0; i < users.size(); i++) {
        User user = users.get(i);
        if (user.isActive() == true) {
            String email = user.getEmail();
            if (email != null) {
                emails.add(email);
            }
        }
    }
    return emails;
}
```

This code has several issues including comparing boolean with == true and using an indexed loop instead of a for-each.
```

With "Smart paste" checked and language on "Auto-detect", click Start Code Review.
Expected: Button shows "Extracting code..." briefly, then code review starts with only the Java method (no markdown, no explanation). Language should be auto-detected as Java.

- [ ] **Step 3: Test with smart paste OFF**

Clear the code review, paste the same text, uncheck "Smart paste", click Start.
Expected: The raw text (with markdown and explanations) is used as-is.

- [ ] **Step 4: Test with clean code (no LLM wrapping)**

With "Smart paste" checked, paste clean code with no markdown or explanations.
Expected: Code passes through unchanged (Claude returns it as-is).

- [ ] **Step 5: Take a screenshot of the working feature**

Capture the host UI showing the code review with extracted clean code.

- [ ] **Step 6: Commit and update backlog**

Update `backlog.md` with this feature as done.
