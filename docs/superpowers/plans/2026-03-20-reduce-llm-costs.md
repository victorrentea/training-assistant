# Reduce LLM Costs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce LLM token usage across all AI features (quiz, summary, debate) by introducing delta-based transcript processing, a provider-agnostic LLM adapter, progressive transcript state, and a live cost dashboard on the host panel.

**Architecture:** Introduce a `TranscriptStateManager` that tracks what transcript text has already been processed and only sends deltas. Wrap all LLM calls behind an `LLMAdapter` interface that tracks token usage and supports provider swapping. Store running clean/summary state server-side. Display cumulative token cost on the host panel via a new badge.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK, vanilla JS

**References:**
- GitHub Issue: #43
- Current LLM call sites: `quiz_core.py` (generate_quiz, refine_quiz), `daemon/summarizer.py` (generate_summary), `daemon/debate_ai.py` (run_debate_ai_cleanup)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `daemon/llm_adapter.py` | **Create** | Provider-agnostic LLM wrapper with token tracking |
| `daemon/transcript_state.py` | **Create** | Delta tracking for transcript text, progressive clean/summary state |
| `daemon/summarizer.py` | **Modify** | Use LLM adapter + transcript deltas instead of full re-reads |
| `quiz_core.py` | **Modify** | Use LLM adapter, cache transcript for refinements |
| `daemon/debate_ai.py` | **Modify** | Use LLM adapter (token tracking only — debate has no transcript waste) |
| `quiz_daemon.py` | **Modify** | Wire up TranscriptStateManager, LLM adapter, POST token usage |
| `state.py` | **Modify** | Add `token_usage` field to AppState |
| `main.py` or `routers/summary.py` | **Modify** | Add `POST /api/token-usage` endpoint |
| `messaging.py` | **Modify** | Include `token_usage` in host state broadcast |
| `static/host.html` | **Modify** | Add token-badge to left status bar |
| `static/host.js` | **Modify** | Render token usage badge with tooltip |
| `tests/test_llm_adapter.py` | **Create** | Unit tests for LLM adapter |
| `tests/test_transcript_state.py` | **Create** | Unit tests for transcript state manager |

---

## Task 1: LLM Adapter with Token Tracking

**Files:**
- Create: `daemon/llm_adapter.py`
- Create: `tests/test_llm_adapter.py`

### Design

```python
# daemon/llm_adapter.py
from dataclasses import dataclass, field
from typing import Optional
import anthropic

# Pricing per 1M tokens (USD) — Claude Sonnet 4.6
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, model: str = ""):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        # Compute cost using model-specific pricing
        pricing = PRICING.get(model, PRICING["claude-sonnet-4-6"])
        self.estimated_cost_usd += (
            input_tokens * pricing["input"] + output_tokens * pricing["output"]
        ) / 1_000_000

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
        }

# Singleton accumulator
_usage = TokenUsage()

def get_usage() -> TokenUsage:
    return _usage

def create_message(api_key: str, model: str, max_tokens: int,
                   messages: list, system: str = "",
                   tools: list | None = None) -> anthropic.types.Message:
    """Thin wrapper around anthropic.Anthropic().messages.create that tracks tokens."""
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    response = client.messages.create(**kwargs)
    _usage.add(response.usage.input_tokens, response.usage.output_tokens, model)
    return response
```

- [ ] **Step 1: Write failing tests for TokenUsage**

```python
# tests/test_llm_adapter.py
from daemon.llm_adapter import TokenUsage, PRICING

def test_token_usage_zero():
    u = TokenUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.estimated_cost_usd == 0.0

def test_token_usage_accumulates():
    u = TokenUsage()
    u.add(1000, 500, "claude-sonnet-4-6")
    u.add(2000, 300, "claude-sonnet-4-6")
    assert u.input_tokens == 3000
    assert u.output_tokens == 800

def test_token_usage_cost_calculation():
    u = TokenUsage()
    u.add(1_000_000, 0)  # 1M input tokens
    assert abs(u.estimated_cost_usd - 3.0) < 0.01  # $3/1M input for sonnet

def test_to_dict():
    u = TokenUsage()
    u.add(100, 50)
    d = u.to_dict()
    assert "input_tokens" in d
    assert "output_tokens" in d
    assert "estimated_cost_usd" in d
    assert d["input_tokens"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/osaka && python3 -m pytest tests/test_llm_adapter.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `daemon/llm_adapter.py`**

Create the file with the design above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_llm_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/llm_adapter.py tests/test_llm_adapter.py
git commit -m "feat: add LLM adapter with token tracking (#43)"
```

---

## Task 2: Wire LLM Adapter into All Call Sites

**Files:**
- Modify: `quiz_core.py` — replace direct `anthropic.Anthropic()` calls with `llm_adapter.create_message()`
- Modify: `daemon/summarizer.py` — same
- Modify: `daemon/debate_ai.py` — same
- Modify: `routers/codereview.py` — same (smart-paste extraction uses Haiku)

### Approach

Each file currently does:
```python
client = anthropic.Anthropic(api_key=...)
response = client.messages.create(model=..., max_tokens=..., messages=..., system=..., tools=...)
```

Replace with:
```python
from daemon.llm_adapter import create_message
response = create_message(api_key=..., model=..., max_tokens=..., messages=..., system=..., tools=...)
```

This is a mechanical substitution. The adapter returns the same `anthropic.types.Message` object, so all downstream code (stop_reason checks, content extraction) stays the same.

**Key call sites to modify:**

1. `quiz_core.py` → `generate_quiz()` (line ~380) — has tool use loop, needs adapter for each iteration
2. `quiz_core.py` → `refine_quiz()` (line ~470) — single call
3. `daemon/summarizer.py` → `generate_summary()` (line ~80) — single call
4. `daemon/debate_ai.py` → `run_debate_ai_cleanup()` (line ~55) — single call
5. `routers/codereview.py` → smart-paste extraction call (uses Haiku) — single call

- [ ] **Step 1: Replace calls in `quiz_core.py`**

Replace `client.messages.create(...)` calls with `create_message(...)`. Remove local `anthropic.Anthropic()` instantiation from those functions.

- [ ] **Step 2: Replace calls in `daemon/summarizer.py`**

Same pattern.

- [ ] **Step 3: Replace calls in `daemon/debate_ai.py`**

Same pattern.

- [ ] **Step 4: Replace call in `routers/codereview.py`**

Same pattern. Note: this call uses Haiku, so ensure the `model` parameter is passed correctly to `create_message()` for accurate cost tracking.

- [ ] **Step 5: Smoke test — start daemon and verify quiz generation still works**

Run: `python3 quiz_daemon.py --dry-run` (or manually trigger quiz generation)

- [ ] **Step 6: Commit**

```bash
git add quiz_core.py daemon/summarizer.py daemon/debate_ai.py routers/codereview.py
git commit -m "refactor: wire LLM adapter into all Claude API call sites (#43)"
```

---

## Task 3: Token Usage Display on Host Panel

**Files:**
- Modify: `state.py` — add `token_usage` dict
- Modify: `main.py` or `routers/summary.py` — add `POST /api/token-usage` endpoint
- Modify: `messaging.py` — include token_usage in host state
- Modify: `static/host.html` — add badge
- Modify: `static/host.js` — render badge
- Modify: `quiz_daemon.py` — POST token usage periodically

### Design

**Backend**: Daemon POSTs `{input_tokens, output_tokens, estimated_cost_usd}` to `/api/token-usage` every 10 seconds (piggyback on existing transcript-status interval). Server stores in `state.token_usage`, broadcasts to host.

**Frontend**: New badge in the left status bar showing `$X.XX` with a tooltip showing token breakdown. Color-coded: green (<$1), yellow ($1-5), red (>$5).

- [ ] **Step 1: Add `token_usage` to AppState in `state.py`**

```python
token_usage: dict = field(default_factory=lambda: {
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0,
})
```

- [ ] **Step 2: Add `POST /api/token-usage` endpoint**

In `routers/summary.py` (or a new router — prefer existing to minimize files).
Note: The daemon authenticates with HTTP Basic Auth (same host credentials) — see existing `_post_json()` calls in `quiz_daemon.py` which pass `config.username, config.password`.

```python
@router.post("/api/token-usage")
async def update_token_usage(data: dict, _=Depends(require_host)):
    state.token_usage = data
    await broadcast_state()
```

- [ ] **Step 3: Include token_usage in `build_host_state()` in `messaging.py`**

Add `"token_usage": state.token_usage` to the host state dict.

- [ ] **Step 4: Add badge HTML in `static/host.html`**

After the `summary-badge` in the left status bar:
```html
<span id="token-badge" class="badge" title="No token data yet">$0.00</span>
```

- [ ] **Step 5: Add JS rendering in `static/host.js`**

```javascript
function updateTokenBadge(usage) {
    const badge = document.getElementById('token-badge');
    if (!badge || !usage) return;
    const cost = usage.estimated_cost_usd || 0;
    badge.textContent = '$' + cost.toFixed(2);
    const inp = (usage.input_tokens || 0).toLocaleString();
    const out = (usage.output_tokens || 0).toLocaleString();
    badge.title = `Tokens: ${inp} in / ${out} out`;
    badge.className = 'badge ' + (cost > 5 ? 'error' : cost > 1 ? 'warning' : 'connected');
}
```

Hook into the existing WebSocket state handler where other badges are updated.

- [ ] **Step 6: Daemon posts token usage periodically**

In `quiz_daemon.py`, alongside the existing transcript-status POST (every 10s):
```python
from daemon.llm_adapter import get_usage
# ... inside the main loop, every 10s:
_post_json(f"{config.server_url}/api/token-usage", get_usage().to_dict(), ...)
```

- [ ] **Step 7: Smoke test — verify badge appears and updates**

Start server + daemon, trigger a quiz generation, verify badge updates on host panel.

- [ ] **Step 8: Commit**

```bash
git add state.py routers/summary.py messaging.py static/host.html static/host.js quiz_daemon.py
git commit -m "feat: display token usage cost on host panel (#43)"
```

---

## Task 4: Transcript Delta Tracking (Progressive State)

**Files:**
- Create: `daemon/transcript_state.py`
- Create: `tests/test_transcript_state.py`
- Modify: `daemon/summarizer.py` — use deltas
- Modify: `quiz_daemon.py` — wire in state manager

### Design

```python
# daemon/transcript_state.py
class TranscriptStateManager:
    """Tracks transcript text already processed, computes deltas."""

    def __init__(self):
        self._last_full_text: str = ""
        self._last_entry_count: int = 0

    def compute_delta(self, entries: list, minutes: int) -> tuple[str, str]:
        """Given parsed transcript entries and a lookback window,
        returns (delta_text, full_text).

        delta_text = only the NEW portion since last call.
        full_text = the complete extracted window (for cases that need it).
        """
        from quiz_core import extract_last_n_minutes
        full_text = extract_last_n_minutes(entries, minutes)

        if not self._last_full_text:
            self._last_full_text = full_text
            self._last_entry_count = len(entries)
            return full_text, full_text  # first call: everything is new

        # Find the new portion: text after the overlap with previous
        # Simple approach: if new text starts with old text, delta is the suffix
        if full_text.startswith(self._last_full_text[:200]):
            # Sliding window moved — find where old text ends in new
            overlap = self._find_overlap(self._last_full_text, full_text)
            delta = full_text[overlap:]
        else:
            delta = full_text  # no overlap detected, send everything

        self._last_full_text = full_text
        self._last_entry_count = len(entries)
        return delta.strip(), full_text

    def _find_overlap(self, old: str, new: str) -> int:
        """Find how many chars from the start of `new` overlap with the end of `old`."""
        # Use last 500 chars of old as anchor
        anchor = old[-500:] if len(old) > 500 else old
        pos = new.find(anchor)
        if pos >= 0:
            return pos + len(anchor)
        return 0  # no overlap found

    def reset(self):
        self._last_full_text = ""
        self._last_entry_count = 0
```

### Applying Deltas to Summary Generation

Currently `generate_summary()` sends the full last-30-min transcript every 5 minutes. With delta tracking:

1. On first call: send full text (same as now)
2. On subsequent calls: send only the delta (new text since last summary), plus locked points as context
3. The system prompt already tells Claude not to repeat locked points — deltas make this more efficient by not re-sending text that produced those points

**Important constraint:** Quiz generation should NOT use deltas — quizzes need full context of the last N minutes to generate good questions. The delta optimization applies primarily to **summaries** (which run every 5 min and accumulate state) and potentially to **future** features.

- [ ] **Step 1: Write failing tests for TranscriptStateManager**

```python
# tests/test_transcript_state.py
def test_first_call_returns_full_text_as_delta():
    ...

def test_second_call_returns_only_new_text():
    ...

def test_reset_clears_state():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `daemon/transcript_state.py`**

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Wire into `daemon/summarizer.py`**

Modify `generate_summary()` to accept an optional `delta_text` parameter. When provided, use delta instead of full text in the prompt (with a note to Claude that this is incremental).

- [ ] **Step 6: Wire into `quiz_daemon.py`**

Create a `TranscriptStateManager` instance for summaries. Before calling `generate_summary()`, compute the delta. Pass delta to summarizer.

- [ ] **Step 7: Smoke test**

- [ ] **Step 8: Commit**

```bash
git add daemon/transcript_state.py tests/test_transcript_state.py daemon/summarizer.py quiz_daemon.py
git commit -m "feat: transcript delta tracking for incremental summaries (#43)"
```

---

## Task 5: Cache Transcript for Quiz Refinements

**Files:**
- Modify: `quiz_core.py` — skip re-sending transcript in refine if unchanged

### Current Problem

`refine_quiz()` sends a 3-message conversation:
1. User: full transcript (60k chars)
2. Assistant: previous quiz JSON
3. User: "regenerate option B"

The transcript in message 1 hasn't changed between generate and refine. But we're paying for it again as input tokens.

### Solution

Since `refine_quiz()` already receives `original_text` from the daemon (which caches it as `last_text`), the caching is already in place at the daemon level. The optimization here is to **shorten the transcript in refine requests**.

Instead of resending the full 60k transcript, send a condensed version:
- Keep the last 5,000 chars of the original transcript (for context)
- Add a note: "The full transcript was provided earlier. Here is the most recent portion for context."

This reduces refine input from ~17k tokens to ~3k tokens.

- [ ] **Step 1: Modify `refine_quiz()` to truncate transcript**

In the refine conversation, replace full `original_text` with a truncated version:
```python
# In refine_quiz():
REFINE_CONTEXT_CHARS = 5_000
truncated = original_text[-REFINE_CONTEXT_CHARS:] if len(original_text) > REFINE_CONTEXT_CHARS else original_text
context_note = f"[Transcript context — last {len(truncated)} chars of {len(original_text)} total]\n{truncated}"
```

- [ ] **Step 2: Test manually — refine a quiz and verify quality is acceptable**

- [ ] **Step 3: Commit**

```bash
git add quiz_core.py
git commit -m "feat: truncate transcript in quiz refinement to reduce tokens (#43)"
```

---

## Execution Order & Dependencies

```
Task 1 (LLM Adapter) ──→ Task 2 (Wire into call sites) ──┬──→ Task 3 (Host panel display)
                                                          ├──→ Task 4 (Transcript deltas)
                                                          └──→ Task 5 (Quiz refine cache)
```

Tasks 3, 4, and 5 can run in parallel after Task 2 is complete.

---

## Expected Token Savings

| Feature | Before (tokens/call) | After (tokens/call) | Savings |
|---------|---------------------|---------------------|---------|
| Quiz refine | ~17,000 input | ~3,000 input | **~82%** |
| Summary (2nd+ call) | ~10,000 input | ~3,000 input (delta) | **~70%** |
| Quiz generate | ~17,000 input | ~17,000 (unchanged) | 0% |
| Debate AI | ~2,500 input | ~2,500 (unchanged) | 0% |

**Per-session estimate** (3h workshop): Quiz refinements (~5x) save ~70k tokens. Summary calls (~36x) save ~250k tokens. Total savings: ~320k tokens/session ≈ **$0.96/session at Sonnet pricing**.
