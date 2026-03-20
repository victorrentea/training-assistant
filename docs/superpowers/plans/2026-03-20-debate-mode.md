# Debate Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Whose Side Are You On?" debate activity where participants pick sides, build arguments, get AI augmentation, and have live debate champions.

**Architecture:** New `ActivityType.DEBATE` with phase-based state machine. Backend: new `routers/debate.py` for REST + WS handlers in `routers/ws.py`. Frontend: new tab + center panel in host, new render function in participant. AI cleanup calls Claude API directly from the debate router.

**Tech Stack:** Python/FastAPI, vanilla JS, Anthropic Claude API, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-20-debate-mode-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `state.py` | Modify (lines 8-12, 27-52) | Add `DEBATE` to `ActivityType`, add debate fields to `AppState.reset()` |
| `routers/debate.py` | Create | REST endpoints: launch, close-selection, phase, ai-cleanup |
| `routers/ws.py` | Modify (after line 164) | WS handlers: `debate_pick_side`, `debate_argument`, `debate_upvote`, `debate_volunteer` |
| `messaging.py` | Modify (lines 21-77, 59-119) | Add `_build_debate_for_participant()`, `_build_debate_for_host()`, include in state builders |
| `main.py` | Modify (line 13, after line 27) | Import and include debate router |
| `static/host.html` | Modify (lines 23-27, 120-144) | Add debate tab button + tab content + center panel |
| `static/host.js` | Modify (lines 890-920) | Add debate tab switching, rendering, host controls |
| `static/host.css` | Modify | Add debate-specific styles (dual-column, phase controls) |
| `static/participant.js` | Modify (lines 372-382) | Add debate activity rendering branch + all debate screens |
| `static/participant.css` | Modify | Add debate styles (dual-column, side selection, arguments) |

---

### Task 1: Add Debate State to Backend

**Files:**
- Modify: `state.py:8-12` (ActivityType enum)
- Modify: `state.py:27-52` (AppState.reset)

- [ ] **Step 1: Add DEBATE to ActivityType enum**

In `state.py`, add after line 12:

```python
class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
    QA = "qa"
    DEBATE = "debate"
```

- [ ] **Step 2: Add debate fields to AppState.reset()**

After `self.summary_updated_at` (line 52), add:

```python
        # Debate state
        self.debate_statement: Optional[str] = None
        self.debate_phase: Optional[str] = None  # "side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"
        self.debate_sides: dict[str, str] = {}  # uuid → "for"|"against"
        self.debate_arguments: list[dict] = []  # [{id, author_uuid, side, text, upvoters: set, ai_generated: bool, merged_into: str|None}]
        self.debate_champions: dict[str, str] = {}  # "for" → uuid, "against" → uuid
```

- [ ] **Step 3: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin && python3 -c "from state import state, ActivityType; print(ActivityType.DEBATE, state.debate_statement)"`
Expected: `debate None`

- [ ] **Step 4: Commit**

```bash
git add state.py
git commit -m "feat(debate): add DEBATE activity type and state fields"
```

---

### Task 2: Create Debate REST Router

**Files:**
- Create: `routers/debate.py`
- Modify: `main.py:13,27` (import and register router)

- [ ] **Step 1: Create routers/debate.py with all endpoints**

```python
import json
import logging
import random
import uuid as uuid_mod
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast_state, participant_ids
from state import state, ActivityType

router = APIRouter()
logger = logging.getLogger(__name__)


class DebateLaunch(BaseModel):
    statement: str


class PhaseAdvance(BaseModel):
    phase: str  # "arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"


@router.post("/api/debate", dependencies=[Depends(require_host_auth)])
async def launch_debate(body: DebateLaunch):
    statement = body.statement.strip()
    if not statement:
        raise HTTPException(400, "Statement cannot be empty")

    # Reset all debate state
    state.debate_statement = statement
    state.debate_phase = "side_selection"
    state.debate_sides = {}
    state.debate_arguments = []
    state.debate_champions = {}
    state.current_activity = ActivityType.DEBATE

    logger.info(f"Debate launched: {statement}")
    await broadcast_state()
    return {"ok": True}


@router.post("/api/debate/close-selection", dependencies=[Depends(require_host_auth)])
async def close_selection():
    if state.debate_phase != "side_selection":
        raise HTTPException(400, "Not in side_selection phase")

    # Auto-assign remaining participants to balance sides
    all_pids = participant_ids()
    assigned = set(state.debate_sides.keys())
    unassigned = [pid for pid in all_pids if pid not in assigned]

    for_count = sum(1 for s in state.debate_sides.values() if s == "for")
    against_count = sum(1 for s in state.debate_sides.values() if s == "against")

    random.shuffle(unassigned)
    for pid in unassigned:
        if for_count <= against_count:
            state.debate_sides[pid] = "for"
            for_count += 1
        else:
            state.debate_sides[pid] = "against"
            against_count += 1

    # Advance to arguments phase (atomic)
    state.debate_phase = "arguments"
    logger.info(f"Selection closed: {for_count} FOR, {against_count} AGAINST")
    await broadcast_state()
    return {"ok": True, "for": for_count, "against": against_count}


VALID_PHASES = {"arguments", "ai_cleanup", "prep", "live_debate", "ended"}


@router.post("/api/debate/phase", dependencies=[Depends(require_host_auth)])
async def advance_phase(body: PhaseAdvance):
    if body.phase not in VALID_PHASES:
        raise HTTPException(400, f"Invalid phase: {body.phase}")
    if not state.debate_statement:
        raise HTTPException(400, "No debate active")

    state.debate_phase = body.phase
    logger.info(f"Debate phase → {body.phase}")
    await broadcast_state()
    return {"ok": True, "phase": body.phase}


@router.post("/api/debate/ai-cleanup", dependencies=[Depends(require_host_auth)])
async def ai_cleanup():
    if state.debate_phase != "ai_cleanup":
        raise HTTPException(400, "Not in ai_cleanup phase")
    if not state.debate_arguments:
        raise HTTPException(400, "No arguments to clean up")

    import os
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")

    # Build prompt
    for_args = [a for a in state.debate_arguments if a["side"] == "for" and not a.get("merged_into")]
    against_args = [a for a in state.debate_arguments if a["side"] == "against" and not a.get("merged_into")]

    prompt = f"""You are helping clean up debate arguments about: "{state.debate_statement}"

FOR arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in for_args)}

AGAINST arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in against_args)}

Tasks:
1. Identify duplicates — return which argument IDs should be merged (keep the better-worded one)
2. For each surviving argument, return a cleaned version (fix typos, make concise, preserve intent)
3. Add 2-4 NEW arguments that participants missed (mark side as "for" or "against")

Return JSON (no markdown fences):
{{
  "merges": [{{"keep_id": "...", "remove_ids": ["..."]}}],
  "cleaned": [{{"id": "...", "text": "cleaned text"}}],
  "new_arguments": [{{"side": "for"|"against", "text": "..."}}]
}}"""

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        result = json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        raise HTTPException(500, "AI returned invalid JSON")

    # Apply merges
    for merge in result.get("merges", []):
        keep_id = merge["keep_id"]
        for remove_id in merge.get("remove_ids", []):
            for arg in state.debate_arguments:
                if arg["id"] == remove_id:
                    arg["merged_into"] = keep_id
                    # Transfer upvotes to kept argument
                    kept = next((a for a in state.debate_arguments if a["id"] == keep_id), None)
                    if kept:
                        kept["upvoters"] = kept["upvoters"] | arg["upvoters"]

    # Apply cleaned text
    for cleaned in result.get("cleaned", []):
        for arg in state.debate_arguments:
            if arg["id"] == cleaned["id"]:
                arg["text"] = cleaned["text"]

    # Add new AI arguments
    for new_arg in result.get("new_arguments", []):
        state.debate_arguments.append({
            "id": str(uuid_mod.uuid4()),
            "author_uuid": "__ai__",
            "side": new_arg["side"],
            "text": new_arg["text"],
            "upvoters": set(),
            "ai_generated": True,
            "merged_into": None,
        })

    logger.info(f"AI cleanup done: {len(result.get('merges', []))} merges, {len(result.get('new_arguments', []))} new args")
    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 2: Register router in main.py**

In `main.py`, add to imports (line 13):
```python
from routers import ws, poll, scores, quiz, pages, wordcloud, activity, qa, summary, debate
```

After line 27, add:
```python
app.include_router(debate.router)
```

- [ ] **Step 3: Verify server starts with new router**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin && python3 -c "from main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'debate' in r])"`
Expected: `['/api/debate', '/api/debate/close-selection', '/api/debate/phase', '/api/debate/ai-cleanup']`

- [ ] **Step 4: Commit**

```bash
git add routers/debate.py main.py
git commit -m "feat(debate): add debate REST router with all endpoints"
```

---

### Task 3: Add Debate WebSocket Handlers

**Files:**
- Modify: `routers/ws.py` (after line 164, before the except block)

- [ ] **Step 1: Add debate WS message handlers**

After the `qa_upvote` handler block (line 164), add:

```python
            elif msg_type == "debate_pick_side":
                side = data.get("side")
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "side_selection"
                    and side in ("for", "against")
                    and pid not in state.debate_sides
                    and not is_host
                ):
                    state.debate_sides[pid] = side
                    await broadcast_state()

            elif msg_type == "debate_argument":
                text = str(data.get("text", "")).strip()
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "arguments"
                    and text
                    and len(text) <= 280
                    and pid in state.debate_sides
                    and not is_host
                ):
                    arg_id = str(uuid_mod.uuid4())
                    state.debate_arguments.append({
                        "id": arg_id,
                        "author_uuid": pid,
                        "side": state.debate_sides[pid],
                        "text": text,
                        "upvoters": set(),
                        "ai_generated": False,
                        "merged_into": None,
                    })
                    state.scores[pid] = state.scores.get(pid, 0) + 100
                    await broadcast_state()

            elif msg_type == "debate_upvote":
                arg_id = data.get("argument_id")
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase in ("arguments", "ai_cleanup", "prep")
                    and not is_host
                ):
                    arg = next((a for a in state.debate_arguments if a["id"] == arg_id), None)
                    if arg and pid not in arg["upvoters"] and arg["author_uuid"] != pid:
                        arg["upvoters"].add(pid)
                        if arg["author_uuid"] != "__ai__":
                            state.scores[arg["author_uuid"]] = state.scores.get(arg["author_uuid"], 0) + 50
                        state.scores[pid] = state.scores.get(pid, 0) + 25
                        await broadcast_state()

            elif msg_type == "debate_volunteer":
                if (
                    state.current_activity == ActivityType.DEBATE
                    and state.debate_phase == "prep"
                    and pid in state.debate_sides
                    and not is_host
                ):
                    my_side = state.debate_sides[pid]
                    if my_side not in state.debate_champions:
                        state.debate_champions[my_side] = pid
                        state.scores[pid] = state.scores.get(pid, 0) + 2500
                        await broadcast_state()
```

- [ ] **Step 2: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin && python3 -m py_compile routers/ws.py && echo "OK"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add routers/ws.py
git commit -m "feat(debate): add WebSocket handlers for side pick, argument, upvote, volunteer"
```

---

### Task 4: Add Debate State to Broadcasts

**Files:**
- Modify: `messaging.py` (add debate builders, update state builders)

- [ ] **Step 1: Add debate state builder functions**

After `_build_qa_for_host()` (after line 56), add:

```python
def _build_debate_for_participant(pid: str) -> dict:
    """Build debate state personalized for a participant."""
    if not state.debate_statement:
        return {}
    my_side = state.debate_sides.get(pid)
    return {
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_my_side": my_side,
        "debate_side_counts": {
            "for": sum(1 for s in state.debate_sides.values() if s == "for"),
            "against": sum(1 for s in state.debate_sides.values() if s == "against"),
        },
        "debate_arguments": [
            {
                "id": a["id"],
                "text": a["text"],
                "side": a["side"],
                "author": "✨ AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "is_own": a["author_uuid"] == pid,
                "has_upvoted": pid in a["upvoters"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
            for a in state.debate_arguments
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
        "debate_my_is_champion": state.debate_champions.get(my_side) == pid if my_side else False,
    }


def _build_debate_for_host() -> dict:
    """Build debate state for host."""
    if not state.debate_statement:
        return {}
    return {
        "debate_statement": state.debate_statement,
        "debate_phase": state.debate_phase,
        "debate_side_counts": {
            "for": sum(1 for s in state.debate_sides.values() if s == "for"),
            "against": sum(1 for s in state.debate_sides.values() if s == "against"),
        },
        "debate_arguments": [
            {
                "id": a["id"],
                "text": a["text"],
                "side": a["side"],
                "author": "✨ AI" if a["ai_generated"] else state.participant_names.get(a["author_uuid"], "Unknown"),
                "author_avatar": "" if a["ai_generated"] else state.participant_avatars.get(a["author_uuid"], ""),
                "ai_generated": a["ai_generated"],
                "upvote_count": len(a["upvoters"]),
                "merged_into": a.get("merged_into"),
            }
            for a in state.debate_arguments
        ],
        "debate_champions": {
            side: state.participant_names.get(uuid, "")
            for side, uuid in state.debate_champions.items()
        },
    }
```

- [ ] **Step 2: Include debate data in participant state builder**

In `build_participant_state()` (line 59-77), add before the closing `}`:

```python
        **_build_debate_for_participant(pid),
```

Add after the `"qa_questions"` line (line 76), so the dict spread merges debate fields into the state.

- [ ] **Step 3: Include debate data in host state builder**

In `build_host_state()` (line 80-119), add before the closing `}`:

```python
        **_build_debate_for_host(),
```

Add after the `"qa_questions"` line (line 118).

- [ ] **Step 4: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin && python3 -c "from messaging import build_participant_state; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add messaging.py
git commit -m "feat(debate): add debate state to participant and host broadcasts"
```

---

### Task 5: Host UI — Tab, Controls, and Center Panel

**Files:**
- Modify: `static/host.html` (lines 23-27 tab bar, lines 99-110 after QA tab, lines 139-144 after QA center)
- Modify: `static/host.js` (lines 890-920 switchTab/updateCenterPanel)
- Modify: `static/host.css`

- [ ] **Step 1: Add debate tab button in host.html**

In the tab bar (line 26), after the Q&A button, add:

```html
      <button class="tab-btn" id="tab-debate" onclick="switchTab('debate')">⚔️ Debate</button>
```

- [ ] **Step 2: Add debate tab content panel in host.html**

After the Q&A tab content `</div>` (line 110), add:

```html
    <!-- Debate tab content -->
    <div id="tab-content-debate" class="tab-content" style="display:none;">
      <div style="margin-top:.75rem;">
        <textarea id="debate-statement-input" rows="2" maxlength="200" placeholder="Enter debate statement…"
          style="width:100%;padding:.5rem .75rem;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:.9rem;resize:vertical;font-family:inherit;"></textarea>
        <button id="debate-launch-btn" class="btn btn-primary" onclick="launchDebate()" style="margin-top:.35rem;">⚔️ Launch Debate</button>
      </div>
      <div id="debate-host-controls" style="display:none; margin-top:.75rem;">
        <div id="debate-phase-label" style="font-size:.85rem; color:var(--muted); margin-bottom:.35rem;"></div>
        <div id="debate-host-actions" class="btn-row"></div>
      </div>
    </div>
```

- [ ] **Step 3: Add debate center panel in host.html**

After the Q&A center panel `</div>` (line 144), add:

```html
    <!-- Debate center panel -->
    <div id="center-debate" class="center-panel" style="display:none;">
      <h2 id="debate-center-title" style="margin:0 0 .5rem; font-size:.95rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em;">⚔️ Debate</h2>
      <div id="debate-statement-display" style="font-size:1.1rem; color:var(--text); margin-bottom:.75rem; font-style:italic;"></div>
      <div id="debate-center-content"></div>
    </div>
```

- [ ] **Step 4: Update switchTab() in host.js**

In `switchTab()` (line 890), add debate tab handling. Replace the entire function:

```javascript
  async function switchTab(tab) {
    ['poll', 'wordcloud', 'qa', 'debate'].forEach(t => {
      document.getElementById('tab-' + t).classList.toggle('active', tab === t);
      document.getElementById('tab-content-' + t).style.display = tab === t ? '' : 'none';
    });
    await fetch('/api/activity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activity: tab }),
    });
  }
```

- [ ] **Step 5: Update updateCenterPanel() in host.js**

Replace the entire function (line 906):

```javascript
  function updateCenterPanel(currentActivity) {
    ['qr', 'poll', 'wordcloud', 'qa', 'debate'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = currentActivity === 'none' ? '' : 'none';
      } else {
        el.style.display = currentActivity === id ? '' : 'none';
      }
    });
    if (currentActivity && currentActivity !== 'none') {
      ['poll', 'wordcloud', 'qa', 'debate'].forEach(t => {
        document.getElementById('tab-' + t).classList.toggle('active', currentActivity === t);
        document.getElementById('tab-content-' + t).style.display = currentActivity === t ? '' : 'none';
      });
    }
  }
```

- [ ] **Step 6: Add host debate rendering functions in host.js**

Add at the end of host.js (before the closing of the IIFE or at file end):

```javascript
  // ── HTML escaping utility ──
  function escDebate(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ── Debate Host Functions ──

  async function launchDebate() {
    const input = document.getElementById('debate-statement-input');
    const statement = input.value.trim();
    if (!statement) return;
    await fetch('/api/debate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ statement }),
    });
  }

  async function debateCloseSelection() {
    await fetch('/api/debate/close-selection', { method: 'POST' });
  }

  async function debateNextPhase(phase) {
    await fetch('/api/debate/phase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase }),
    });
  }

  async function debateRunAI() {
    const btn = document.querySelector('#debate-host-actions .btn-ai');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Running AI…'; }
    try {
      await fetch('/api/debate/ai-cleanup', { method: 'POST' });
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨ Run AI Cleanup'; }
    }
  }

  function renderDebateHost(msg) {
    if (!msg.debate_statement) return;

    const controls = document.getElementById('debate-host-controls');
    const phaseLabel = document.getElementById('debate-phase-label');
    const actions = document.getElementById('debate-host-actions');
    const title = document.getElementById('debate-statement-display');
    const content = document.getElementById('debate-center-content');

    controls.style.display = '';
    title.textContent = '"' + msg.debate_statement + '"';

    const phase = msg.debate_phase;
    const sideCounts = msg.debate_side_counts || { for: 0, against: 0 };

    // Phase label
    const phaseNames = {
      side_selection: 'Phase 1: Side Selection',
      arguments: 'Phase 2: Arguments',
      ai_cleanup: 'Phase 3: AI Cleanup',
      prep: 'Phase 4: Preparation',
      live_debate: 'Phase 5: Live Debate',
      ended: 'Debate Ended',
    };
    phaseLabel.textContent = (phaseNames[phase] || phase) +
      ` — FOR: ${sideCounts.for} | AGAINST: ${sideCounts.against}`;

    // Host action buttons per phase
    actions.innerHTML = '';
    if (phase === 'side_selection') {
      actions.innerHTML = '<button class="btn btn-primary" onclick="debateCloseSelection()">🔒 Close Selection → Arguments</button>';
    } else if (phase === 'arguments') {
      actions.innerHTML = '<button class="btn btn-primary" onclick="debateNextPhase(\'ai_cleanup\')">Next → AI Cleanup</button>';
    } else if (phase === 'ai_cleanup') {
      actions.innerHTML = '<button class="btn btn-warn btn-ai" onclick="debateRunAI()">✨ Run AI Cleanup</button>' +
        ' <button class="btn btn-primary" onclick="debateNextPhase(\'prep\')">Next → Preparation</button>';
    } else if (phase === 'prep') {
      const champions = msg.debate_champions || {};
      const champInfo = Object.entries(champions).map(([s, n]) => `${s}: ${n}`).join(', ');
      actions.innerHTML = (champInfo ? `<span style="color:var(--accent);font-size:.85rem;">🏆 ${champInfo}</span> ` : '') +
        '<button class="btn btn-primary" onclick="debateNextPhase(\'live_debate\')">▶ Start Live Debate</button>';
    } else if (phase === 'live_debate') {
      actions.innerHTML = '<button class="btn btn-danger" onclick="debateNextPhase(\'ended\')">⏹ End Debate</button>';
    }

    // Center panel: dual-column arguments
    const args = (msg.debate_arguments || []).filter(a => !a.merged_into);
    const forArgs = args.filter(a => a.side === 'for');
    const againstArgs = args.filter(a => a.side === 'against');
    const mergedArgs = (msg.debate_arguments || []).filter(a => a.merged_into);

    if (phase === 'side_selection') {
      content.innerHTML = `<div style="text-align:center; padding:2rem; color:var(--muted);">
        Waiting for participants to choose sides…<br>
        <span style="font-size:1.5rem; margin-top:.5rem; display:block;">
          👍 FOR: ${sideCounts.for} &nbsp;|&nbsp; 👎 AGAINST: ${sideCounts.against}
        </span>
      </div>`;
    } else {
      content.innerHTML = renderDebateDualColumn(againstArgs, forArgs, mergedArgs, msg.debate_champions, phase);
    }
  }

  function renderDebateDualColumn(againstArgs, forArgs, mergedArgs, champions, phase) {
    const renderArg = (a) => {
      const aiClass = a.ai_generated ? ' debate-arg-ai' : '';
      return `<div class="debate-arg${aiClass}" data-id="${a.id}">
        <div class="debate-arg-header">
          ${a.author_avatar ? `<img src="/static/avatars/${a.author_avatar}" class="debate-arg-avatar">` : ''}
          <span class="debate-arg-author">${escDebate(a.author)}</span>
          <span class="debate-arg-votes">▲ ${a.upvote_count}</span>
        </div>
        <div class="debate-arg-text">${escDebate(a.text)}</div>
      </div>`;
    };

    const renderMerged = () => `<div class="debate-arg debate-arg-merged">
      <span style="color:var(--muted);font-size:.8rem;">✨ duplicate, merged above</span>
    </div>`;

    const champFor = champions?.for ? `<div class="debate-champion">🏆 ${escDebate(champions.for)}</div>` : '';
    const champAgainst = champions?.against ? `<div class="debate-champion">🏆 ${escDebate(champions.against)}</div>` : '';

    // Show hints in prep/live_debate
    let hints = '';
    if (phase === 'prep' || phase === 'live_debate') {
      hints = `<div class="debate-hints">
        <div class="debate-hint">💡 In what context does this trade-off matter most?</div>
        <div class="debate-hint">💡 What's the strongest counterargument?</div>
        <div class="debate-hint">💡 Give specific examples from real projects</div>
        <div class="debate-hint">💡 Present your strongest argument first</div>
      </div>`;
    }

    // Count merged args per side for "merged above" placeholders
    const mergedForCount = mergedArgs.filter(a => a.side === 'for').length;
    const mergedAgainstCount = mergedArgs.filter(a => a.side === 'against').length;

    return `<div class="debate-columns">
      <div class="debate-col debate-col-against">
        <h3 class="debate-col-header">👎 AGAINST</h3>
        ${champAgainst}
        ${againstArgs.map(renderArg).join('')}
        ${Array(mergedAgainstCount).fill('').map(renderMerged).join('')}
      </div>
      <div class="debate-col debate-col-for">
        <h3 class="debate-col-header">👍 FOR</h3>
        ${champFor}
        ${forArgs.map(renderArg).join('')}
        ${Array(mergedForCount).fill('').map(renderMerged).join('')}
      </div>
    </div>${hints}`;
  }
```

Make sure `launchDebate`, `debateCloseSelection`, `debateNextPhase`, `debateRunAI` are accessible globally (attach to `window` if inside an IIFE).

- [ ] **Step 7: Add debate styles to host.css**

Append to `static/host.css`:

```css
/* Debate dual-column layout */
.debate-columns { display: flex; gap: 1rem; min-height: 200px; }
.debate-col { flex: 1; display: flex; flex-direction: column; gap: .5rem; }
.debate-col-header { margin: 0 0 .5rem; font-size: .85rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.debate-col-against { border-right: 1px solid var(--border); padding-right: 1rem; }
.debate-arg { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: .5rem .75rem; }
.debate-arg-header { display: flex; align-items: center; gap: .4rem; margin-bottom: .25rem; }
.debate-arg-avatar { width: 20px; height: 20px; border-radius: 50%; }
.debate-arg-author { font-size: .8rem; color: var(--muted); }
.debate-arg-votes { margin-left: auto; font-size: .8rem; color: var(--accent); }
.debate-arg-text { font-size: .9rem; color: var(--text); }
.debate-arg-merged { opacity: .5; font-style: italic; }
.debate-champion { font-size: .85rem; color: var(--accent); margin-bottom: .25rem; }
.debate-hints { margin-top: 1rem; padding: .75rem; background: var(--surface2); border-radius: 8px; border: 1px solid var(--border); }
.debate-hint { font-size: .85rem; color: var(--muted); margin: .25rem 0; }
```

- [ ] **Step 8: Wire renderDebateHost into the main state handler in host.js**

Find the state message handler in host.js where `updateCenterPanel(msg.current_activity)` is called. After that call, add:

```javascript
        if (msg.current_activity === 'debate') {
          renderDebateHost(msg);
        } else {
          // Hide debate controls when not in debate
          const dc = document.getElementById('debate-host-controls');
          if (dc) dc.style.display = 'none';
        }
```

- [ ] **Step 9: Verify host page loads without errors**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin && python3 -m uvicorn main:app --port 8765 &` then open http://localhost:8765/host in browser, check console for errors. Kill server after.

- [ ] **Step 10: Commit**

```bash
git add static/host.html static/host.js static/host.css
git commit -m "feat(debate): add host UI — tab, controls, center panel with dual-column"
```

---

### Task 6: Participant UI — All Debate Phases

**Files:**
- Modify: `static/participant.js` (lines 372-382, add renderDebateScreen)
- Modify: `static/participant.css`

- [ ] **Step 1: Add debate branch to participant state handler**

In `handleMessage` (participant.js line 372-382), change:

```javascript
        if (msg.current_activity === 'wordcloud') {
```

to add debate handling. After the `} else if (msg.current_activity === 'qa') {` block and before the `} else {`, add:

```javascript
        } else if (msg.current_activity === 'debate') {
          renderDebateScreen(msg);
```

Also add notification (after the wordcloud notification block, around line 339):

```javascript
          if (_prevActivity !== 'debate' && msg.current_activity === 'debate') {
            notifyIfHidden('⚔️ Debate started', 'Choose your side!');
          }
```

- [ ] **Step 2: Add renderDebateScreen function**

Add to participant.js:

```javascript
  // ── HTML escaping utility ──
  function escDebate(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ── Debate rendering ──
  function renderDebateScreen(msg) {
    const content = document.getElementById('content');
    if (!content) return;
    content.dataset.screen = 'debate';

    const phase = msg.debate_phase;
    const mySide = msg.debate_my_side;
    const statement = msg.debate_statement || '';
    const sideCounts = msg.debate_side_counts || { for: 0, against: 0 };
    const args = (msg.debate_arguments || []).filter(a => !a.merged_into);
    const champions = msg.debate_champions || {};
    const readOnly = phase === 'ai_cleanup' || phase === 'ended';

    if (!statement) {
      content.innerHTML = '<div class="debate-waiting">Waiting for debate to start…</div>';
      return;
    }

    let html = `<div class="debate-statement">"${escDebate(statement)}"</div>`;

    if (phase === 'side_selection') {
      if (mySide) {
        html += `<div class="debate-chosen">You chose: <strong>${mySide.toUpperCase()}</strong> ✓</div>`;
        html += `<div class="debate-waiting">Waiting for others… FOR: ${sideCounts.for} | AGAINST: ${sideCounts.against}</div>`;
      } else {
        html += `<div class="debate-pick">
          <button class="btn debate-btn-for" onclick="debatePickSide('for')">👍 FOR</button>
          <button class="btn debate-btn-against" onclick="debatePickSide('against')">👎 AGAINST</button>
        </div>`;
      }
    } else if (phase === 'arguments') {
      html += renderDebateArgColumns(args, mySide, msg, false);
      if (mySide) {
        html += `<div class="debate-input-row">
          <input id="debate-arg-input" type="text" maxlength="280" placeholder="Add an argument for your side…"
            onkeydown="if(event.key==='Enter')debateSubmitArg()" />
          <button class="btn btn-primary" onclick="debateSubmitArg()">↵</button>
        </div>`;
      }
    } else if (phase === 'ai_cleanup') {
      html += `<div class="debate-phase-info">AI is reviewing arguments…</div>`;
      html += renderDebateArgColumns(args, mySide, msg, true);  // read-only
    } else if (phase === 'prep') {
      html += renderDebateArgColumns(args, mySide, msg, false);
      html += renderDebateHints();
      if (mySide && !champions[mySide]) {
        html += `<button class="btn btn-warn debate-volunteer-btn" onclick="debateVolunteer()">🏆 I'll be our champion!</button>`;
      } else if (mySide && champions[mySide]) {
        const isMe = msg.debate_my_is_champion;
        html += `<div class="debate-champion-info">${isMe ? '🏆 You are your team\'s champion!' : '🏆 Champion: ' + champions[mySide]}</div>`;
      }
    } else if (phase === 'live_debate') {
      html += renderDebateArgColumns(args, mySide, msg, true);  // read-only during live debate
      html += renderDebateHints();
      const champNames = Object.entries(champions).map(([s, n]) => `${s.toUpperCase()}: ${escDebate(n)}`).join(' vs ');
      html += `<div class="debate-live-info">🎤 ${champNames}</div>`;
    } else if (phase === 'ended') {
      html += `<div class="debate-ended">Debate ended!</div>`;
      html += renderDebateArgColumns(args, mySide, msg, true);
    }

    content.innerHTML = html;
  }

  function renderDebateArgColumns(args, mySide, msg, readOnly) {
    const forArgs = args.filter(a => a.side === 'for');
    const againstArgs = args.filter(a => a.side === 'against');
    const mergedArgs = (msg.debate_arguments || []).filter(a => a.merged_into);
    const mergedForCount = mergedArgs.filter(a => a.side === 'for').length;
    const mergedAgainstCount = mergedArgs.filter(a => a.side === 'against').length;

    const renderArg = (a) => {
      const aiClass = a.ai_generated ? ' debate-arg-ai' : '';
      const ownClass = a.is_own ? ' debate-arg-own' : '';
      const upvotedClass = a.has_upvoted ? ' debate-arg-upvoted' : '';
      const canUpvote = !readOnly && !a.is_own && !a.has_upvoted;
      return `<div class="debate-arg${aiClass}${ownClass}${upvotedClass}" ${canUpvote ? `onclick="debateUpvote('${a.id}')"` : ''}>
        <div class="debate-arg-header">
          ${a.author_avatar ? `<img src="/static/avatars/${a.author_avatar}" class="debate-arg-avatar">` : ''}
          <span class="debate-arg-author">${escDebate(a.author)}</span>
          <span class="debate-arg-votes">▲ ${a.upvote_count}</span>
        </div>
        <div class="debate-arg-text">${escDebate(a.text)}</div>
      </div>`;
    };

    const renderMerged = () => `<div class="debate-arg debate-arg-merged">
      <span>✨ duplicate, merged above</span>
    </div>`;

    return `<div class="debate-columns">
      <div class="debate-col debate-col-against">
        <h3 class="debate-col-header">👎 AGAINST</h3>
        ${againstArgs.map(renderArg).join('')}
        ${Array(mergedAgainstCount).fill('').map(renderMerged).join('')}
      </div>
      <div class="debate-col debate-col-for">
        <h3 class="debate-col-header">👍 FOR</h3>
        ${forArgs.map(renderArg).join('')}
        ${Array(mergedForCount).fill('').map(renderMerged).join('')}
      </div>
    </div>`;
  }

  function renderDebateHints() {
    return `<div class="debate-hints">
      <div class="debate-rules-title">📋 Debate Rules</div>
      <div class="debate-hint">• Present your strongest argument first</div>
      <div class="debate-hint">• Address the opposing argument directly</div>
      <div class="debate-hint">• Give specific examples from real projects</div>
      <div class="debate-hint">• In what context does this trade-off matter most?</div>
    </div>`;
  }

  // ── Debate WS senders ──
  function debatePickSide(side) {
    if (ws) ws.send(JSON.stringify({ type: 'debate_pick_side', side }));
  }

  function debateSubmitArg() {
    const input = document.getElementById('debate-arg-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'debate_argument', text }));
    input.value = '';
  }

  function debateUpvote(argId) {
    if (ws) ws.send(JSON.stringify({ type: 'debate_upvote', argument_id: argId }));
  }

  function debateVolunteer() {
    if (ws) ws.send(JSON.stringify({ type: 'debate_volunteer' }));
  }
```

Make sure all `debatePickSide`, `debateSubmitArg`, `debateUpvote`, `debateVolunteer` are accessible from HTML onclick (attach to `window` if inside IIFE).

- [ ] **Step 3: Add participant debate styles**

Append to `static/participant.css`:

```css
/* Debate styles */
.debate-statement { font-size: 1.1rem; color: var(--text); font-style: italic; text-align: center; margin-bottom: 1rem; padding: .75rem; background: var(--surface2); border-radius: 8px; }
.debate-pick { display: flex; gap: 1rem; justify-content: center; margin: 1.5rem 0; }
.debate-btn-for, .debate-btn-against { flex: 1; max-width: 200px; padding: 1.5rem 1rem; font-size: 1.2rem; border-radius: 12px; border: 2px solid var(--border); cursor: pointer; }
.debate-btn-for { background: rgba(46, 204, 113, .15); color: #2ecc71; }
.debate-btn-for:hover { background: rgba(46, 204, 113, .3); }
.debate-btn-against { background: rgba(231, 76, 60, .15); color: #e74c3c; }
.debate-btn-against:hover { background: rgba(231, 76, 60, .3); }
.debate-chosen { text-align: center; font-size: 1.1rem; color: var(--accent); margin: 1rem 0; }
.debate-waiting { text-align: center; font-size: .9rem; color: var(--muted); }
.debate-columns { display: flex; gap: .75rem; margin: .75rem 0; }
.debate-col { flex: 1; display: flex; flex-direction: column; gap: .4rem; }
.debate-col-header { margin: 0 0 .4rem; font-size: .8rem; color: var(--muted); text-transform: uppercase; text-align: center; }
.debate-col-against { border-right: 1px solid var(--border); padding-right: .75rem; }
.debate-arg { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: .4rem .6rem; cursor: pointer; transition: border-color .15s; }
.debate-arg:hover { border-color: var(--accent); }
.debate-arg-upvoted { border-color: var(--accent); }
.debate-arg-own { border-left: 3px solid var(--accent); }
.debate-arg-header { display: flex; align-items: center; gap: .3rem; margin-bottom: .15rem; }
.debate-arg-avatar { width: 18px; height: 18px; border-radius: 50%; }
.debate-arg-author { font-size: .75rem; color: var(--muted); }
.debate-arg-votes { margin-left: auto; font-size: .75rem; color: var(--accent); }
.debate-arg-text { font-size: .85rem; color: var(--text); }
.debate-arg-merged { opacity: .5; font-style: italic; font-size: .8rem; color: var(--muted); }
.debate-input-row { display: flex; gap: .5rem; margin-top: .75rem; }
.debate-input-row input { flex: 1; padding: .5rem .75rem; border-radius: 8px; border: 1px solid var(--border); background: var(--surface2); color: var(--text); font-size: .9rem; }
.debate-phase-info { text-align: center; color: var(--muted); font-size: .9rem; margin: .5rem 0; }
.debate-volunteer-btn { display: block; margin: 1rem auto; padding: .75rem 1.5rem; font-size: 1rem; }
.debate-champion-info { text-align: center; color: var(--accent); font-size: 1rem; margin: 1rem 0; }
.debate-hints { margin-top: .75rem; padding: .5rem .75rem; background: var(--surface2); border-radius: 8px; border: 1px solid var(--border); }
.debate-rules-title { font-size: .85rem; color: var(--accent); margin-bottom: .25rem; }
.debate-hint { font-size: .8rem; color: var(--muted); margin: .15rem 0; }
.debate-live-info { text-align: center; font-size: 1rem; color: var(--accent); margin-top: .75rem; }
.debate-ended { text-align: center; font-size: 1.1rem; color: var(--muted); margin: 1rem 0; }
```

- [ ] **Step 4: Verify participant page loads**

Open http://localhost:8765/ in browser, check console for errors.

- [ ] **Step 5: Commit**

```bash
git add static/participant.js static/participant.css
git commit -m "feat(debate): add participant UI for all debate phases"
```

---

### Task 7: Update Activity Switch for Debate

**Files:**
- Modify: `routers/activity.py:12` (update comment)

- [ ] **Step 1: Update ActivitySwitch comment**

In `routers/activity.py`, line 12, update the comment:

```python
class ActivitySwitch(BaseModel):
    activity: str  # "poll" | "wordcloud" | "qa" | "debate" | "none"
```

This is just a comment update — the enum validation already handles the new value since we added `DEBATE = "debate"` to `ActivityType`.

- [ ] **Step 2: Commit**

```bash
git add routers/activity.py
git commit -m "docs: update ActivitySwitch comment to include debate"
```

---

### Task 8: End-to-End Manual Test

**Files:** None (testing only)

- [ ] **Step 1: Start server**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/dublin
python3 -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Test full debate flow**

Open http://localhost:8000/host in one tab, http://localhost:8000/ in two participant tabs.

1. Click ⚔️ Debate tab in host
2. Type "Microservices are better than monoliths" → Launch
3. In participant tabs: click FOR / AGAINST
4. In host: Close Selection
5. In participant tabs: submit arguments
6. Verify arguments appear in correct columns on both host and participant
7. Click arguments to upvote — verify counter increments and scores change
8. In host: Next → AI Cleanup → Run AI (if ANTHROPIC_API_KEY set) → Next
9. In participant: click "I'll be our champion!" → verify champion shows
10. In host: Start Live Debate → verify hints shown → End Debate

- [ ] **Step 3: Fix any issues found**

- [ ] **Step 4: Final commit if fixes were needed**

```bash
git add -A
git commit -m "fix(debate): fixes from end-to-end testing"
```

---

### Task 9: Update Sequence Diagram

**Files:**
- Modify: `adoc/seq_debate_flow.puml` (if any changes were made to the flow during implementation)

- [ ] **Step 1: Review diagram against implementation**

Read `adoc/seq_debate_flow.puml` and verify it matches the implemented flow. Update any discrepancies.

- [ ] **Step 2: Commit if changes were made**

```bash
git add adoc/seq_debate_flow.puml
git commit -m "docs: sync debate sequence diagram with implementation"
```
