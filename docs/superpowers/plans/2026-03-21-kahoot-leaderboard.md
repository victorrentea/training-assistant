# Kahoot-Style Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dramatic Kahoot-style top-5 leaderboard reveal triggered by the host, with auto-assigned movie character names in conference mode.

**Architecture:** New `names.py` module for the character name pool. New `routers/leaderboard.py` router for show/hide endpoints. Personalized WS broadcast for leaderboard data (same pattern as `broadcast_state()`). Frontend overlays on both host and participant sides with sequential animation.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, WebSocket broadcasts.

**Spec:** `docs/superpowers/specs/2026-03-21-kahoot-leaderboard-design.md`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `names.py` | Character name pool + assignment + letter avatar color computation |
| Create | `routers/leaderboard.py` | `/api/leaderboard/show` and `/api/leaderboard/hide` endpoints |
| Modify | `state.py:27-83` | Add `leaderboard_active`, `participant_universes` fields |
| Modify | `routers/ws.py:84-88` | Replace empty-string conference name with auto-assigned character name |
| Modify | `messaging.py:201-227` | Include leaderboard data for late joiners in `build_participant_state()` |
| Modify | `messaging.py:284-298` | Add `broadcast_leaderboard()` helper (personalized per-participant) |
| Modify | `main.py:27-38` | Mount leaderboard router |
| Modify | `static/host.html:23-29` | Add Leaderboard button to tab bar |
| Modify | `static/host.js:1127-1138` | Leaderboard button handler + overlay rendering + sequential animation |
| Modify | `static/host.js:518-558` | Avatar rendering: detect `letter:` prefix |
| Modify | `static/participant.html:19-42` | Add leaderboard overlay container |
| Modify | `static/participant.js:453-487` | Avatar rendering: detect `letter:` prefix |
| Modify | `static/participant.js:1299-1316` | Conference mode: show edit icon, handle leaderboard WS message |
| Modify | `static/host.css` | Leaderboard overlay + animation styles |
| Modify | `static/participant.css` | Leaderboard overlay styles |

---

### Task 1: Character Name Pool (`names.py`)

**Files:**
- Create: `names.py`

- [ ] **Step 1: Create `names.py` with character pool and helper functions**

```python
"""Character name pool for conference mode auto-assignment."""
import hashlib

CHARACTER_NAMES: list[tuple[str, str]] = [
    # Star Wars
    ("Yoda", "Star Wars"), ("Luke", "Star Wars"), ("Leia", "Star Wars"),
    ("Han Solo", "Star Wars"), ("Chewbacca", "Star Wars"), ("Obi-Wan", "Star Wars"),
    ("Darth Vader", "Star Wars"), ("Palpatine", "Star Wars"), ("Mace Windu", "Star Wars"),
    ("Ahsoka", "Star Wars"), ("Boba Fett", "Star Wars"), ("Jango Fett", "Star Wars"),
    ("Padme", "Star Wars"), ("Anakin", "Star Wars"), ("Rey", "Star Wars"),
    ("Kylo Ren", "Star Wars"), ("Finn", "Star Wars"), ("Poe", "Star Wars"),
    ("Lando", "Star Wars"), ("Jabba", "Star Wars"), ("Grievous", "Star Wars"),
    ("Dooku", "Star Wars"), ("Maul", "Star Wars"), ("Qui-Gon", "Star Wars"),
    ("R2-D2", "Star Wars"), ("C-3PO", "Star Wars"), ("BB-8", "Star Wars"),
    ("Grogu", "Star Wars"), ("Mandalorian", "Star Wars"), ("Tarkin", "Star Wars"),
    # LOTR
    ("Gandalf", "LOTR"), ("Frodo", "LOTR"), ("Aragorn", "LOTR"),
    ("Legolas", "LOTR"), ("Gimli", "LOTR"), ("Samwise", "LOTR"),
    ("Boromir", "LOTR"), ("Faramir", "LOTR"), ("Gollum", "LOTR"),
    ("Saruman", "LOTR"), ("Elrond", "LOTR"), ("Galadriel", "LOTR"),
    ("Theoden", "LOTR"), ("Eowyn", "LOTR"), ("Eomer", "LOTR"),
    ("Treebeard", "LOTR"), ("Sauron", "LOTR"), ("Pippin", "LOTR"),
    ("Merry", "LOTR"), ("Arwen", "LOTR"), ("Bilbo", "LOTR"),
    ("Radagast", "LOTR"), ("Haldir", "LOTR"), ("Denethor", "LOTR"),
    # Matrix
    ("Neo", "Matrix"), ("Morpheus", "Matrix"), ("Trinity", "Matrix"),
    ("Agent Smith", "Matrix"), ("Oracle", "Matrix"), ("Niobe", "Matrix"),
    ("Cypher", "Matrix"), ("Tank", "Matrix"), ("Apoc", "Matrix"),
    ("Mouse", "Matrix"), ("Dozer", "Matrix"), ("Merovingian", "Matrix"),
    ("Seraph", "Matrix"), ("Architect", "Matrix"), ("Keymaker", "Matrix"),
    # Marvel
    ("Iron Man", "Marvel"), ("Thor", "Marvel"), ("Hulk", "Marvel"),
    ("Black Widow", "Marvel"), ("Hawkeye", "Marvel"), ("Spider-Man", "Marvel"),
    ("Black Panther", "Marvel"), ("Doctor Strange", "Marvel"), ("Scarlet Witch", "Marvel"),
    ("Vision", "Marvel"), ("Ant-Man", "Marvel"), ("Wasp", "Marvel"),
    ("Captain Marvel", "Marvel"), ("Falcon", "Marvel"), ("Groot", "Marvel"),
    ("Rocket", "Marvel"), ("Gamora", "Marvel"), ("Drax", "Marvel"),
    ("Star-Lord", "Marvel"), ("Nebula", "Marvel"), ("Thanos", "Marvel"),
    ("Loki", "Marvel"), ("Shang-Chi", "Marvel"), ("Moon Knight", "Marvel"),
    ("Wolverine", "Marvel"), ("Deadpool", "Marvel"), ("Storm", "Marvel"),
    ("Magneto", "Marvel"), ("Professor X", "Marvel"), ("Cyclops", "Marvel"),
    # Star Trek
    ("Kirk", "Star Trek"), ("Spock", "Star Trek"), ("McCoy", "Star Trek"),
    ("Scotty", "Star Trek"), ("Uhura", "Star Trek"), ("Sulu", "Star Trek"),
    ("Chekov", "Star Trek"), ("Picard", "Star Trek"), ("Riker", "Star Trek"),
    ("Data", "Star Trek"), ("Worf", "Star Trek"), ("Troi", "Star Trek"),
    ("Crusher", "Star Trek"), ("LaForge", "Star Trek"), ("Janeway", "Star Trek"),
    ("Seven of Nine", "Star Trek"), ("Tuvok", "Star Trek"), ("Sisko", "Star Trek"),
    ("Odo", "Star Trek"), ("Quark", "Star Trek"),
    # Harry Potter
    ("Harry Potter", "HP"), ("Hermione", "HP"), ("Ron Weasley", "HP"),
    ("Dumbledore", "HP"), ("Snape", "HP"), ("Voldemort", "HP"),
    ("Hagrid", "HP"), ("McGonagall", "HP"), ("Sirius Black", "HP"),
    ("Lupin", "HP"), ("Draco Malfoy", "HP"), ("Dobby", "HP"),
    ("Luna", "HP"), ("Neville", "HP"), ("Bellatrix", "HP"),
    ("Moody", "HP"), ("Tonks", "HP"), ("Cedric", "HP"),
    ("Fred Weasley", "HP"), ("George Weasley", "HP"),
    # Dune
    ("Paul Atreides", "Dune"), ("Chani", "Dune"), ("Duncan Idaho", "Dune"),
    ("Stilgar", "Dune"), ("Lady Jessica", "Dune"), ("Baron Harkonnen", "Dune"),
    ("Feyd-Rautha", "Dune"), ("Leto Atreides", "Dune"), ("Gurney Halleck", "Dune"),
    ("Thufir Hawat", "Dune"), ("Alia", "Dune"), ("Irulan", "Dune"),
    # Back to the Future
    ("Doc Brown", "BTTF"), ("Marty McFly", "BTTF"), ("Biff Tannen", "BTTF"),
    ("Jennifer Parker", "BTTF"), ("Lorraine", "BTTF"), ("George McFly", "BTTF"),
    # Blade Runner
    ("Deckard", "Blade Runner"), ("Roy Batty", "Blade Runner"), ("Rachael", "Blade Runner"),
    ("Pris", "Blade Runner"), ("K", "Blade Runner"), ("Joi", "Blade Runner"),
    ("Gaff", "Blade Runner"), ("Tyrell", "Blade Runner"),
    # Hitchhiker's Guide
    ("Arthur Dent", "H2G2"), ("Ford Prefect", "H2G2"), ("Zaphod", "H2G2"),
    ("Trillian", "H2G2"), ("Marvin", "H2G2"), ("Deep Thought", "H2G2"),
    ("Slartibartfast", "H2G2"),
    # Alien/Aliens
    ("Ripley", "Alien"), ("Bishop", "Alien"), ("Newt", "Alien"),
    ("Hicks", "Alien"), ("Dallas", "Alien"), ("Ash", "Alien"),
    # Terminator
    ("T-800", "Terminator"), ("Sarah Connor", "Terminator"), ("John Connor", "Terminator"),
    ("T-1000", "Terminator"), ("Kyle Reese", "Terminator"),
    # The Expanse
    ("Holden", "Expanse"), ("Naomi", "Expanse"), ("Amos", "Expanse"),
    ("Alex", "Expanse"), ("Bobbie", "Expanse"), ("Avasarala", "Expanse"),
    ("Miller", "Expanse"), ("Drummer", "Expanse"),
    # Firefly
    ("Mal Reynolds", "Firefly"), ("Zoe", "Firefly"), ("Wash", "Firefly"),
    ("Inara", "Firefly"), ("Kaylee", "Firefly"), ("Jayne", "Firefly"),
    ("River Tam", "Firefly"), ("Simon Tam", "Firefly"), ("Shepherd", "Firefly"),
    # Tron
    ("Flynn", "Tron"), ("Tron", "Tron"), ("Quorra", "Tron"),
    ("Rinzler", "Tron"), ("CLU", "Tron"),
    # DC
    ("Batman", "DC"), ("Superman", "DC"), ("Wonder Woman", "DC"),
    ("Flash", "DC"), ("Aquaman", "DC"), ("Green Lantern", "DC"),
    ("Joker", "DC"), ("Catwoman", "DC"), ("Harley Quinn", "DC"),
    ("Alfred", "DC"), ("Robin", "DC"), ("Cyborg", "DC"),
    # Video Games
    ("Mario", "Nintendo"), ("Link", "Zelda"), ("Samus", "Metroid"),
    ("Master Chief", "Halo"), ("Kratos", "God of War"), ("Geralt", "Witcher"),
    ("Commander Shepard", "Mass Effect"), ("Gordon Freeman", "Half-Life"),
    ("GLaDOS", "Portal"), ("Chell", "Portal"),
    ("Solid Snake", "Metal Gear"), ("Lara Croft", "Tomb Raider"),
    ("Ezio", "Assassin's Creed"), ("Joel", "Last of Us"), ("Ellie", "Last of Us"),
    ("Cloud", "FF7"), ("Tifa", "FF7"), ("Sephiroth", "FF7"),
    ("Aloy", "Horizon"), ("Kirby", "Nintendo"),
    # Misc Sci-Fi
    ("HAL 9000", "2001"), ("Dave Bowman", "2001"),
    ("Optimus Prime", "Transformers"), ("Megatron", "Transformers"),
    ("Wall-E", "Pixar"), ("EVE", "Pixar"),
    ("Godzilla", "Kaiju"), ("Mothra", "Kaiju"),
    ("Robocop", "Robocop"), ("Judge Dredd", "2000 AD"),
    ("The Doctor", "Doctor Who"), ("Dalek", "Doctor Who"),
    ("Sherlock", "BBC"), ("John Watson", "BBC"),
]


def compute_letter_avatar(name: str) -> tuple[str, str]:
    """Return (2-letter code, hex color) for a name.
    Letters = first 2 chars of name uppercased.
    Color = deterministic hash-based HSL color.
    """
    letters = name.replace("-", "").replace(" ", "")[:2].upper()
    if len(letters) < 2:
        letters = letters.ljust(2, "X")
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    hue = h % 360
    sat = 55 + (h >> 8) % 25   # 55-80%
    lum = 45 + (h >> 16) % 15  # 45-60%
    color = f"hsl({hue},{sat}%,{lum}%)"
    return letters, color


def assign_conference_name(state) -> tuple[str, str]:
    """Pick a random unused character name for a new conference participant.
    Returns (name, universe). Unused = not assigned to any currently connected UUID.
    """
    import random
    connected_uuids = {uid for uid in state.participants if not uid.startswith("__")}
    used_names = {state.participant_names.get(uid) for uid in connected_uuids
                  if uid in state.participant_names}
    available = [(n, u) for n, u in CHARACTER_NAMES if n not in used_names]
    if available:
        return random.choice(available)
    short_id = hex(random.randint(0, 0xFFFF))[2:].upper()
    return (f"Hero-{short_id}", "")
```

Pool has ~300 entries across 25+ universes. The `compute_letter_avatar` function produces deterministic 2-letter codes and HSL colors. `assign_conference_name` checks only connected UUIDs so names are recycled when participants disconnect.

- [ ] **Step 2: Verify the module loads and pool count is sufficient**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dallas && python3 -c "from names import CHARACTER_NAMES, compute_letter_avatar, assign_conference_name; print(f'{len(CHARACTER_NAMES)} names'); print(compute_letter_avatar('Yoda')); print(compute_letter_avatar('Neo'))"`

Expected: ~280+ names, 2-letter codes like `('YO', 'hsl(...)')` and `('NE', 'hsl(...)')`.

- [ ] **Step 3: Commit**

```bash
git add names.py
git commit -m "feat: add character name pool for conference mode (#49)"
```

---

### Task 2: State Model Changes (`state.py`)

**Files:**
- Modify: `state.py:27-83` (AppState.reset method)

- [ ] **Step 1: Add `leaderboard_active` and `participant_universes` to AppState**

In `state.py`, inside the `reset()` method, add after the existing `participant_avatars` line:

```python
self.participant_universes: dict[str, str] = {}  # uuid → universe string
self.leaderboard_active: bool = False
```

- [ ] **Step 2: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dallas && timeout 5 python3 -m uvicorn main:app --port 18765 2>&1 || true`

Expected: Server starts without import errors.

- [ ] **Step 3: Commit**

```bash
git add state.py
git commit -m "feat: add leaderboard_active and participant_universes to AppState (#49)"
```

---

### Task 3: Conference Name Auto-Assignment (`routers/ws.py`)

**Files:**
- Modify: `routers/ws.py:84-88` (conference mode name assignment)
- Modify: `routers/ws.py:126-133` (set_name handler — update universe on rename)

- [ ] **Step 1: Replace empty-string conference assignment with character name**

In `routers/ws.py`, replace lines 84-88:

```python
# OLD:
if state.mode == "conference" and not named:
    state.participant_names[pid] = ""
    named = True
    await websocket.send_text(json.dumps(build_participant_state(pid)))
```

With:

```python
if state.mode == "conference" and not named:
    from names import assign_conference_name, compute_letter_avatar
    char_name, universe = assign_conference_name(state)
    state.participant_names[pid] = char_name
    state.participant_universes[pid] = universe
    letters, color = compute_letter_avatar(char_name)
    state.participant_avatars[pid] = f"letter:{letters}:{color}"
    named = True
    await websocket.send_text(json.dumps(build_participant_state(pid)))
```

- [ ] **Step 2: Update set_name handler to clear universe on rename**

In `routers/ws.py`, in the `set_name` handler (around line 126-133), add after `state.participant_names[pid] = name`:

```python
if state.mode == "conference":
    from names import compute_letter_avatar
    state.participant_universes[pid] = ""  # custom name, no universe
    letters, color = compute_letter_avatar(name)
    state.participant_avatars[pid] = f"letter:{letters}:{color}"
```

- [ ] **Step 3: Verify by starting server and checking logs**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dallas && timeout 5 python3 -m uvicorn main:app --port 18765 2>&1 || true`

Expected: No import errors.

- [ ] **Step 4: Commit**

```bash
git add routers/ws.py
git commit -m "feat: auto-assign character names in conference mode (#49)"
```

---

### Task 4: Leaderboard Router (`routers/leaderboard.py`)

**Files:**
- Create: `routers/leaderboard.py`
- Modify: `main.py:27-38` (mount the router)

- [ ] **Step 1: Create `routers/leaderboard.py`**

```python
"""Leaderboard show/hide endpoints."""
from fastapi import APIRouter, Depends
from auth import require_host_auth
from state import state
from messaging import broadcast_leaderboard, broadcast

router = APIRouter()


@router.post("/api/leaderboard/show", dependencies=[Depends(require_host_auth)])
async def show_leaderboard():
    state.leaderboard_active = True
    await broadcast_leaderboard()
    return {"ok": True}


@router.post("/api/leaderboard/hide", dependencies=[Depends(require_host_auth)])
async def hide_leaderboard():
    state.leaderboard_active = False
    await broadcast({"type": "leaderboard_hide"})
    return {"ok": True}
```

- [ ] **Step 2: Mount in `main.py`**

In `main.py`, add import:
```python
from routers import leaderboard
```

Add after the other `app.include_router(...)` lines:
```python
app.include_router(leaderboard.router)
```

- [ ] **Step 3: Commit**

```bash
git add routers/leaderboard.py main.py
git commit -m "feat: add leaderboard show/hide endpoints (#49)"
```

---

### Task 5: Leaderboard Broadcast Logic (`messaging.py`)

**Files:**
- Modify: `messaging.py` — add `broadcast_leaderboard()` function
- Modify: `messaging.py:201-227` — include leaderboard data for late joiners

- [ ] **Step 1: Add `broadcast_leaderboard()` function**

Add this function after `broadcast_state()` (around line 298):

```python
async def broadcast_leaderboard():
    """Send personalized leaderboard to each connected participant."""
    from names import compute_letter_avatar

    # Build top 5 by score
    scored = [(uid, state.scores.get(uid, 0)) for uid in state.participants
              if not uid.startswith("__") and state.scores.get(uid, 0) > 0]
    scored.sort(key=lambda x: (-x[1], state.participant_names.get(x[0], "")))
    top5 = scored[:5]

    entries = []
    for rank_idx, (uid, score) in enumerate(top5):
        name = state.participant_names.get(uid, "Unknown")
        universe = state.participant_universes.get(uid, "")
        avatar = state.participant_avatars.get(uid, "")
        if avatar.startswith("letter:"):
            parts = avatar.split(":", 2)
            letter = parts[1] if len(parts) > 1 else "??"
            color = parts[2] if len(parts) > 2 else "hsl(0,60%,50%)"
        else:
            letter, color = compute_letter_avatar(name)
        entries.append({
            "rank": rank_idx + 1,
            "name": name,
            "universe": universe,
            "score": score,
            "letter": letter,
            "color": color,
            "avatar": avatar,
        })

    total = len([uid for uid in state.participants if not uid.startswith("__")])

    # Build full ranking for personal rank lookup
    all_scored = [(uid, state.scores.get(uid, 0)) for uid in state.participants
                  if not uid.startswith("__")]
    all_scored.sort(key=lambda x: (-x[1], state.participant_names.get(x[0], "")))
    rank_map = {uid: idx + 1 for idx, (uid, _) in enumerate(all_scored)}

    # Send personalized message to each participant
    dead = []
    for pid, ws in state.participants.items():
        if pid == "__overlay__":
            continue
        try:
            is_participant = not pid.startswith("__")
            msg = {
                "type": "leaderboard",
                "entries": entries,
                "total_participants": total,
                "your_rank": rank_map.get(pid) if is_participant else None,
                "your_score": state.scores.get(pid, 0) if is_participant else None,
                "your_name": state.participant_names.get(pid, "") if is_participant else None,
            }
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)
```

- [ ] **Step 2: Stop suppressing avatar/name in conference mode for `build_participant_state()`**

In `messaging.py`, in `build_participant_state()`, change the `my_avatar` line (around line 217) from:
```python
"my_avatar": "" if state.mode == "conference" else state.participant_avatars.get(pid, ""),
```
to:
```python
"my_avatar": state.participant_avatars.get(pid, ""),
```

Conference mode letter avatars need to reach the participant so they can see their identity in the status bar and on the leaderboard. The "anonymous" behavior is preserved by not showing scores, not by hiding the avatar.

Also add `leaderboard_active` and `my_name` to the returned dict:
```python
"leaderboard_active": state.leaderboard_active,
"my_name": state.participant_names.get(pid, ""),
```

- [ ] **Step 3: Send leaderboard to late joiners in ws.py**

In `routers/ws.py`, after the initial state is sent to a new connection (after `await websocket.send_text(json.dumps(build_participant_state(pid)))`), add:

```python
if state.leaderboard_active:
    await broadcast_leaderboard()
```

This re-sends to everyone (idempotent — the overlay just re-renders). Import `broadcast_leaderboard` from `messaging` at the top of the file.

- [ ] **Step 4: Verify server starts**

Run: `cd /Users/victorrentea/conductor/workspaces/training-assistant/dallas && timeout 5 python3 -m uvicorn main:app --port 18765 2>&1 || true`

Expected: No import errors.

- [ ] **Step 5: Commit**

```bash
git add messaging.py routers/ws.py
git commit -m "feat: add leaderboard broadcast with personalized ranks (#49)"
```

---

### Task 6: Host UI — Leaderboard Button + Overlay (`host.html`, `host.js`, `host.css`)

**Files:**
- Modify: `static/host.html:23-29` (tab bar — add leaderboard button)
- Modify: `static/host.html` (add overlay container in center column)
- Modify: `static/host.js` (button handler, WS message handler, animation)
- Modify: `static/host.css` (overlay + animation styles)

- [ ] **Step 1: Add leaderboard button to tab bar in `host.html`**

In `static/host.html`, after the last tab button (Debate), add:

```html
<button class="tab-btn leaderboard-btn" id="btn-leaderboard" onclick="toggleLeaderboard()" title="Show Leaderboard" disabled>
  <span class="tab-icon">🏆</span>Board
</button>
```

- [ ] **Step 2: Add leaderboard overlay container in host.html**

Inside the center column (`host-col-center`), add at the end:

```html
<div id="leaderboard-overlay" class="leaderboard-overlay" style="display:none;">
  <div class="leaderboard-content">
    <button class="leaderboard-close" onclick="toggleLeaderboard()">&times;</button>
    <h1 class="leaderboard-title">LEADERBOARD</h1>
    <div id="leaderboard-entries" class="leaderboard-entries"></div>
  </div>
</div>
```

- [ ] **Step 3: Add leaderboard CSS to `host.css`**

Append to `static/host.css`:

```css
/* Leaderboard button */
.leaderboard-btn {
  margin-left: auto;
  background: var(--surface2) !important;
  border: 1px solid var(--accent) !important;
}
.leaderboard-btn:not(:disabled):hover {
  background: var(--accent) !important;
}
.leaderboard-btn:disabled {
  opacity: .4;
  cursor: not-allowed;
}

/* Leaderboard overlay */
.leaderboard-overlay {
  position: absolute;
  inset: 0;
  background: rgba(15, 17, 23, 0.95);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.5s ease;
}
.leaderboard-content {
  text-align: center;
  width: 100%;
  max-width: 600px;
  padding: 2rem;
  position: relative;
}
.leaderboard-close {
  position: absolute;
  top: 0; right: 0;
  background: none;
  border: none;
  color: var(--muted);
  font-size: 2rem;
  cursor: pointer;
}
.leaderboard-close:hover { color: var(--text); }
.leaderboard-title {
  font-size: 2.5rem;
  letter-spacing: .3em;
  color: var(--accent);
  margin-bottom: 2rem;
  text-transform: uppercase;
}
.leaderboard-entries {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.leaderboard-entry {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  background: var(--surface);
  border-radius: 12px;
  border: 1px solid var(--border);
  opacity: 0;
  transform: translateY(40px);
}
.leaderboard-entry.visible {
  animation: slideUp 0.5s ease forwards;
}
.leaderboard-entry.first-place {
  border-color: gold;
  box-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
  font-size: 1.2em;
}
.leaderboard-rank {
  font-size: 1.8rem;
  font-weight: 900;
  color: var(--accent);
  min-width: 2.5rem;
}
.first-place .leaderboard-rank { color: gold; }
.leaderboard-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 1rem;
  color: #fff;
  flex-shrink: 0;
}
.leaderboard-name {
  flex: 1;
  text-align: left;
  font-weight: 600;
  color: var(--text);
}
.leaderboard-universe {
  color: var(--muted);
  font-weight: 400;
  font-size: .85em;
}
.leaderboard-score {
  font-weight: 800;
  color: var(--accent2);
  font-size: 1.3rem;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(40px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 4: Add leaderboard JavaScript to `host.js`**

Add at the end of `host.js`:

```javascript
// ── Leaderboard ──────────────────────────────────────
let _leaderboardActive = false;

async function toggleLeaderboard() {
    if (_leaderboardActive) {
        await fetch('/api/leaderboard/hide', { method: 'POST' });
    } else {
        await fetch('/api/leaderboard/show', { method: 'POST' });
    }
}

function renderLeaderboard(data) {
    _leaderboardActive = true;
    const overlay = document.getElementById('leaderboard-overlay');
    const entriesEl = document.getElementById('leaderboard-entries');
    overlay.style.display = 'flex';
    entriesEl.innerHTML = '';

    const btn = document.getElementById('btn-leaderboard');
    if (btn) btn.classList.add('active');

    // Render entries bottom-to-top with sequential animation
    const entries = data.entries || [];
    entries.forEach((entry, i) => {
        const div = document.createElement('div');
        div.className = 'leaderboard-entry' + (entry.rank === 1 ? ' first-place' : '');

        const avatarStyle = entry.avatar && entry.avatar.startsWith('letter:')
            ? `background:${entry.color}`
            : `background:var(--surface2)`;
        const avatarContent = entry.avatar && entry.avatar.startsWith('letter:')
            ? entry.letter
            : '';
        const avatarImg = entry.avatar && !entry.avatar.startsWith('letter:')
            ? `<img src="/static/avatars/${entry.avatar}" style="width:48px;height:48px;border-radius:50%" onerror="this.style.display='none'">`
            : '';

        const universeTag = entry.universe
            ? ` <span class="leaderboard-universe">(${entry.universe})</span>`
            : '';

        div.innerHTML = `
            <span class="leaderboard-rank">#${entry.rank}</span>
            ${avatarImg || `<span class="leaderboard-avatar" style="${avatarStyle}">${avatarContent}</span>`}
            <span class="leaderboard-name">${escHtml(entry.name)}${universeTag}</span>
            <span class="leaderboard-score">${entry.score} pts</span>
        `;
        entriesEl.appendChild(div);

        // Sequential reveal: 5th first (bottom), 1st last (top)
        // entries are ordered 1→5, but we reveal 5→1
        const revealDelay = (entries.length - 1 - i) * 800;
        setTimeout(() => div.classList.add('visible'), 500 + revealDelay);
    });
}

function hideLeaderboard() {
    _leaderboardActive = false;
    const overlay = document.getElementById('leaderboard-overlay');
    overlay.style.display = 'none';
    const btn = document.getElementById('btn-leaderboard');
    if (btn) btn.classList.remove('active');
}

function updateLeaderboardButton(participantCount, scores) {
    const btn = document.getElementById('btn-leaderboard');
    if (!btn) return;
    const scoredCount = Object.values(scores || {}).filter(s => s > 0).length;
    btn.disabled = scoredCount < 5;
}
```

- [ ] **Step 5: Wire up WS message handling in host.js**

In the existing WebSocket `onmessage` handler in `host.js`, add cases for `leaderboard` and `leaderboard_hide`:

```javascript
if (msg.type === 'leaderboard') {
    renderLeaderboard(msg);
    return;
}
if (msg.type === 'leaderboard_hide') {
    hideLeaderboard();
    return;
}
```

Also, in the handler for `state` messages (or `participant_count`), call:
```javascript
updateLeaderboardButton(msg.count, scores);
```

- [ ] **Step 6: Test manually — open host panel, verify button appears disabled**

Open `http://localhost:8000/host` in browser and verify the Leaderboard button is visible in the tab bar but disabled.

- [ ] **Step 7: Commit**

```bash
git add static/host.html static/host.js static/host.css
git commit -m "feat: add leaderboard overlay with dramatic reveal on host (#49)"
```

---

### Task 7: Participant UI — Leaderboard Overlay (`participant.html`, `participant.js`, `participant.css`)

**Files:**
- Modify: `static/participant.html` (add overlay container)
- Modify: `static/participant.js` (WS handler, overlay rendering)
- Modify: `static/participant.css` (overlay styles)

- [ ] **Step 1: Add leaderboard overlay container to `participant.html`**

Add before `</body>`:

```html
<div id="leaderboard-overlay" class="leaderboard-overlay" style="display:none;">
  <div class="leaderboard-content">
    <div id="leaderboard-my-rank" class="leaderboard-my-rank"></div>
    <div id="leaderboard-top5" class="leaderboard-top5"></div>
  </div>
</div>
```

- [ ] **Step 2: Add leaderboard CSS to `participant.css`**

Append to `static/participant.css`:

```css
/* Leaderboard overlay */
.leaderboard-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 23, 0.97);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  animation: lbFadeIn 0.5s ease;
  padding: 1.5rem;
}
.leaderboard-content {
  text-align: center;
  width: 100%;
  max-width: 400px;
}
.leaderboard-my-rank {
  margin-bottom: 2rem;
}
.leaderboard-my-rank .rank-number {
  font-size: 4rem;
  font-weight: 900;
  color: var(--accent);
}
.leaderboard-my-rank .rank-total {
  font-size: 1.1rem;
  color: var(--muted);
}
.leaderboard-my-rank .rank-score {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent2);
  margin-top: .5rem;
}
.leaderboard-top5 {
  display: flex;
  flex-direction: column;
  gap: .6rem;
}
.lb-entry {
  display: flex;
  align-items: center;
  gap: .7rem;
  padding: .7rem 1rem;
  background: var(--surface);
  border-radius: 10px;
  border: 1px solid var(--border);
}
.lb-entry.is-me {
  border-color: var(--accent);
  box-shadow: 0 0 12px rgba(108, 99, 255, 0.3);
}
.lb-entry.first-place {
  border-color: gold;
  box-shadow: 0 0 12px rgba(255, 215, 0, 0.3);
}
.lb-rank {
  font-size: 1.2rem;
  font-weight: 900;
  color: var(--accent);
  min-width: 2rem;
}
.lb-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: .75rem;
  color: #fff;
  flex-shrink: 0;
}
.lb-name { flex: 1; text-align: left; font-weight: 600; font-size: .9rem; }
.lb-universe { color: var(--muted); font-size: .75rem; }
.lb-score { font-weight: 800; color: var(--accent2); font-size: 1rem; }
@keyframes lbFadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
```

- [ ] **Step 3: Add leaderboard WS handler in `participant.js`**

In the `onmessage` handler in `participant.js`, add:

```javascript
if (msg.type === 'leaderboard') {
    showParticipantLeaderboard(msg);
    return;
}
if (msg.type === 'leaderboard_hide') {
    hideParticipantLeaderboard();
    return;
}
```

Add the rendering functions:

```javascript
// ── Leaderboard ──────────────────────────────────────
function showParticipantLeaderboard(data) {
    const overlay = document.getElementById('leaderboard-overlay');
    const myRankEl = document.getElementById('leaderboard-my-rank');
    const top5El = document.getElementById('leaderboard-top5');
    overlay.style.display = 'flex';

    myRankEl.innerHTML = `
        <div class="rank-number">#${data.your_rank || '?'}</div>
        <div class="rank-total">out of ${data.total_participants}</div>
        <div class="rank-score">${data.your_score || 0} pts</div>
    `;

    top5El.innerHTML = (data.entries || []).map(e => {
        const isMe = data.your_name && data.your_name === e.name;
        const isFirst = e.rank === 1;
        const cls = 'lb-entry' + (isMe ? ' is-me' : '') + (isFirst ? ' first-place' : '');

        const avatarStyle = e.avatar && e.avatar.startsWith('letter:')
            ? `background:${e.color}` : `background:var(--surface2)`;
        const avatarContent = e.avatar && e.avatar.startsWith('letter:')
            ? e.letter : '';
        const avatarImg = e.avatar && !e.avatar.startsWith('letter:')
            ? `<img src="/static/avatars/${e.avatar}" style="width:32px;height:32px;border-radius:50%" onerror="this.style.display='none'">`
            : '';
        const universe = e.universe ? ` <span class="lb-universe">(${e.universe})</span>` : '';

        return `<div class="${cls}">
            <span class="lb-rank">#${e.rank}</span>
            ${avatarImg || `<span class="lb-avatar" style="${avatarStyle}">${avatarContent}</span>`}
            <span class="lb-name">${e.name}${universe}</span>
            <span class="lb-score">${e.score} pts</span>
        </div>`;
    }).join('');
}

function hideParticipantLeaderboard() {
    document.getElementById('leaderboard-overlay').style.display = 'none';
}
```

- [ ] **Step 4: Commit**

```bash
git add static/participant.html static/participant.js static/participant.css
git commit -m "feat: add leaderboard overlay on participant side (#49)"
```

---

### Task 8: Letter Avatar Rendering in Existing UI

**Files:**
- Modify: `static/host.js:518-558` (participant list avatar rendering)
- Modify: `static/participant.js:453-487` (participant avatar rendering)

- [ ] **Step 1: Update host.js avatar rendering in `renderParticipantList`**

In `host.js`, in `renderParticipantList` (around line 527), replace the avatar rendering:

```javascript
// OLD:
const avatarHtml = avatar
    ? `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`
    : '';
```

With:

```javascript
let avatarHtml = '';
if (avatar && avatar.startsWith('letter:')) {
    const parts = avatar.split(':');
    const lt = parts[1] || '??';
    const clr = parts.slice(2).join(':') || 'var(--muted)';
    avatarHtml = `<span class="avatar letter-avatar" style="width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:.65rem;color:#fff;background:${clr}">${lt}</span>`;
} else if (avatar) {
    avatarHtml = `<img src="/static/avatars/${escHtml(avatar)}" class="avatar" style="width:28px;height:28px" onerror="this.style.display='none'">`;
}
```

- [ ] **Step 2: Update participant.js avatar rendering**

In `participant.js`, in the state message handler where `msg.my_avatar` is processed (around line 453), add a check before the existing image logic:

```javascript
if (msg.my_avatar && msg.my_avatar.startsWith('letter:')) {
    const avatarEl = document.getElementById('my-avatar');
    const parts = msg.my_avatar.split(':');
    const lt = parts[1] || '??';
    const clr = parts.slice(2).join(':') || 'var(--muted)';
    // Replace img with span if needed
    const existing = document.getElementById('my-avatar');
    if (existing && existing.tagName === 'IMG') {
        const span = document.createElement('span');
        span.id = 'my-avatar';
        span.className = 'avatar letter-avatar';
        span.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-weight:800;font-size:.65rem;color:#fff;background:' + clr;
        span.textContent = lt;
        existing.replaceWith(span);
    } else if (existing) {
        existing.style.background = clr;
        existing.textContent = lt;
        existing.style.display = '';
    }
} else if (msg.my_avatar) {
    // existing image avatar logic
```

- [ ] **Step 3: Commit**

```bash
git add static/host.js static/participant.js
git commit -m "feat: support letter avatars in participant list and status bar (#49)"
```

---

### Task 9: Conference Mode — Edit Name Icon on Participant

**Files:**
- Modify: `static/participant.js:1299-1316` (applyParticipantMode)

- [ ] **Step 1: Show edit button and name in conference mode**

In `participant.js`, modify `applyParticipantMode` to NOT fully hide status-left in conference mode. Instead, show the name + edit icon but hide score/location/notif:

```javascript
function applyParticipantMode(mode) {
    const isConference = mode === 'conference';
    const statusLeft = document.querySelector('.status-left');
    if (statusLeft) statusLeft.style.display = '';  // always visible now

    // In conference mode: show name + edit icon, hide score
    const myScore = document.getElementById('my-score');
    if (myScore) myScore.style.display = isConference ? 'none' : '';

    const editBtn = document.getElementById('edit-name-btn');
    if (editBtn) editBtn.style.display = '';  // always show edit button

    // Rest stays the same...
```

- [ ] **Step 2: Commit**

```bash
git add static/participant.js
git commit -m "feat: show edit-name icon in conference mode (#49)"
```

---

### Task 10: End-to-End Manual Test

- [ ] **Step 1: Start server locally**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/dallas
python3 -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Test conference mode flow**

1. Open host panel (`http://localhost:8000/host`), switch to conference mode
2. Open 5+ participant tabs (`http://localhost:8000/`)
3. Verify each participant gets a character name (visible in server logs or WS messages)
4. Do a poll or word cloud activity so participants earn points
5. Click Leaderboard button on host — verify:
   - Dramatic overlay with sequential reveal (5th → 1st)
   - Each entry shows letter avatar, name (universe), score
   - Participant tabs show their rank overlay
6. Click again to dismiss — verify overlays disappear on all tabs

- [ ] **Step 3: Test workshop mode flow**

1. Switch back to workshop mode
2. Verify leaderboard button still works
3. Verify image avatars show instead of letter avatars on leaderboard

- [ ] **Step 4: Take screenshots as proof**

- [ ] **Step 5: Update CLAUDE.md auth scope**

Add `/api/leaderboard/show` and `/api/leaderboard/hide` to the auth scope list in CLAUDE.md.

- [ ] **Step 6: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update auth scope with leaderboard endpoints (#49)"
```
