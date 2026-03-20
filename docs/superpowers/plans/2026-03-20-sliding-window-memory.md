# Sliding Window with Long-Term Bullet Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent early-session summary bullets from being lost after ~2 hours by splitting bullets into locked (code-preserved) and draft (LLM-editable) tiers.

**Architecture:** The daemon maintains two local lists: `locked_points` (append-only history) and `draft_points` (last cycle's output). Each cycle, draft promotes to locked, Claude generates only new bullets, and the concatenated list is posted to the server. No backend or frontend changes.

**Tech Stack:** Python 3.12, Anthropic Claude API, FastAPI (unchanged)

**Spec:** `docs/superpowers/specs/2026-03-20-sliding-window-memory-design.md`

---

### Task 1: Update summarizer prompt and function signature

**Files:**
- Modify: `daemon/summarizer.py:26-50` (system prompt)
- Modify: `daemon/summarizer.py:53-56` (function signature)
- Modify: `daemon/summarizer.py:77-85` (user message construction)
- Modify: `daemon/summarizer.py:135-138` (remove date bullet injection)

- [ ] **Step 1: Replace the system prompt**

Replace `_SUMMARY_SYSTEM_PROMPT` (lines 26-50) with:

```python
_SUMMARY_SYSTEM_PROMPT = """\
You are a technical workshop summarizer. You extract high-density takeaways from a live session.

Input: transcript excerpt, optionally trainer's session notes, optionally established key points from earlier in the session.

Output rules:
- Each bullet: ONE actionable or factual technical statement (max 15 words).
- Write like a cheat-sheet: name patterns, tools, trade-offs, rules-of-thumb, commands, gotchas.
- GOOD: "Extract Method refactoring reduces cyclomatic complexity per function"
- GOOD: "@Transactional on private methods is silently ignored by Spring AOP"
- BAD: "Participants shared experiences about refactoring" (vague, no knowledge)
- BAD: "Session ended with informal discussion" (filler, no takeaway)
- BAD: "The trainer demonstrated an interesting approach" (meta-commentary)
- Never describe what happened socially — only capture WHAT was taught or concluded.
- Output 1-7 NEW bullets covering genuinely new takeaways not already in the established list.
- Do NOT repeat, rephrase, or contradict established key points — they are already captured.
- Ignore transcription noise, filler, off-topic chatter.
- For each bullet, indicate source:
  - "notes" if it comes primarily from SESSION NOTES (trainer's agenda/material)
  - "discussion" if it comes primarily from TRANSCRIPT (what was actually said)

Return ONLY a JSON array of objects. No markdown, no explanation.
Example: [{"text": "Outbox pattern decouples DB writes from message publishing", "source": "discussion"}]
"""
```

- [ ] **Step 2: Update function signature**

Change lines 53-56 from:
```python
def generate_summary(
    config: Config,
    existing_points: list[dict],
) -> Optional[list[dict]]:
```
to:
```python
def generate_summary(
    config: Config,
    locked_points: list[dict],
) -> Optional[list[dict]]:
```

Update docstring to: `"""Generate new summary points from transcript, given locked (read-only) context. Returns list of new bullets only, or None on failure."""`

- [ ] **Step 3: Update user message construction**

Replace lines 77-85 with:
```python
    # Build user message
    parts = []
    if notes:
        parts.append(f"SESSION NOTES (trainer's agenda):\n{notes}\n")
    if locked_points:
        locked_texts = "\n".join(f"- {p['text']}" for p in locked_points)
        parts.append(f"ESTABLISHED KEY POINTS (read-only reference — do NOT repeat or rephrase these):\n{locked_texts}\n")
    parts.append(f"TRANSCRIPT (last {DEFAULT_TRANSCRIPT_MINUTES} minutes):\n{text}")

    user_message = "\n---\n".join(parts)
```

- [ ] **Step 4: Remove date bullet injection**

Remove lines 135-138 (the date bullet prepend logic):
```python
        # Prepend today's date as the first bullet
        date_text = f"Session date: {date.today().isoformat()}"
        points = [p for p in points if not p["text"].startswith("Session date:")]
        points.insert(0, {"text": date_text, "source": "notes"})
```

Also remove the `from datetime import date` import (line 10) since it's no longer used here.

- [ ] **Step 5: Commit**

```bash
git add daemon/summarizer.py
git commit -m "refactor: summarizer generates only new bullets with locked context"
```

---

### Task 2: Update daemon to manage locked/draft state

**Files:**
- Modify: `quiz_daemon.py:252-254` (state initialization)
- Modify: `quiz_daemon.py:405-421` (summary generation loop)

- [ ] **Step 1: Verify `date` import exists**

Confirm `from datetime import date` is already imported at line 24 of `quiz_daemon.py` (used for `last_detected_date`). No change needed.

- [ ] **Step 2: Update state initialization**

Replace lines 252-254:
```python
    # Summary state
    summary_points: list[dict] = []
    last_summary_at = 0.0  # monotonic time of last summary run
```
with:
```python
    # Summary state — two-tier: locked (preserved) + draft (reshapeable)
    locked_points: list[dict] = [
        {"text": f"Session date: {date.today().isoformat()}", "source": "notes"}
    ]
    draft_points: list[dict] = []
    last_summary_at = 0.0  # monotonic time of last summary run
```

- [ ] **Step 3: Update summary generation block**

Replace lines 411-421 (the full try/except block inside the summary generation section):
```python
                try:
                    new_points = generate_summary(config, summary_points)
                    if new_points is not None:
                        summary_points = new_points
                        _post_json(
                            f"{config.server_url}/api/summary",
                            {"points": summary_points},
                            config.host_username, config.host_password,
                        )
                except Exception as e:
                    print(f"[summarizer] Error during summary generation: {e}", file=sys.stderr)
```
with:
```python
                try:
                    # Promote draft → locked before generating
                    locked_points.extend(draft_points)
                    draft_points = []
                    new_points = generate_summary(config, locked_points)
                    if new_points is not None:
                        draft_points = new_points
                        all_points = locked_points + draft_points
                        _post_json(
                            f"{config.server_url}/api/summary",
                            {"points": all_points},
                            config.host_username, config.host_password,
                        )
                        print(f"[summarizer] {len(locked_points)} locked + {len(draft_points)} draft = {len(all_points)} total points")
                except Exception as e:
                    print(f"[summarizer] Error during summary generation: {e}", file=sys.stderr)
```

- [ ] **Step 4: Commit**

```bash
git add quiz_daemon.py
git commit -m "feat: two-tier locked/draft bullet memory for summary persistence"
```

---

### Task 3: Verify and test

- [ ] **Step 1: Syntax check both files**

```bash
python3 -c "import py_compile; py_compile.compile('daemon/summarizer.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('quiz_daemon.py', doraise=True)"
```

Expected: no errors.

- [ ] **Step 2: Review the full diff**

```bash
git diff master -- daemon/summarizer.py quiz_daemon.py
```

Verify:
- `summarizer.py` no longer imports `date`
- `summarizer.py` no longer injects the session date bullet
- `summarizer.py` function takes `locked_points`, sends them as read-only context
- `quiz_daemon.py` initializes `locked_points` with date bullet
- `quiz_daemon.py` promotes draft→locked before each call
- `quiz_daemon.py` posts concatenated list

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add daemon/summarizer.py quiz_daemon.py
git commit -m "fix: address review findings in sliding window memory"
```
