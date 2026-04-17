# AgentMail Webhook via Railway — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 60-second polling LaunchAgent with an event-driven flow: AgentMail webhooks Railway → Railway forwards via WebSocket → local listener runs Claude only when an email arrives.

**Architecture:** A new `railway/features/inbox/router.py` adds two endpoints: a webhook receiver (`POST /webhook/agentmail`) and a persistent WebSocket (`GET /ws/claude-inbox`). A lightweight Python script on the Mac connects to that WebSocket, runs a catch-up scan on every connect, then waits for `email_received` events to trigger Claude.

**Tech Stack:** FastAPI/WebSocket (Railway, Python), `websockets` lib (local listener, via uv inline deps), macOS LaunchAgent plist.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `railway/shared/state.py` | Modify | Add `claude_inbox_ws: WebSocket \| None` field |
| `railway/features/inbox/__init__.py` | Create | Package marker |
| `railway/features/inbox/router.py` | Create | Webhook POST + WebSocket endpoints |
| `railway/app.py` | Modify | Mount inbox router |
| `tests/unit/test_inbox_router.py` | Create | Unit tests for webhook auth and forwarding |
| `~/.claude/inbox-ws-listener.py` | Create | Local Mac listener script |
| `~/Library/LaunchAgents/ro.victorrentea.claude-inbox-ws.plist` | Create | New persistent LaunchAgent |
| `~/.claude/agentmail.env` | Modify | Add `CLAUDE_INBOX_WS_TOKEN` |
| `secrets.env` | Modify | Add Railway env var names (values go in Railway dashboard) |

---

### Task 1: Add `claude_inbox_ws` to AppState

**Files:**
- Modify: `railway/shared/state.py:47-76` (inside `reset()`)

- [ ] **Step 1: Add the field in `reset()`**

In `railway/shared/state.py`, inside `reset()`, add after `self.daemon_ws`:
```python
        self.claude_inbox_ws: WebSocket | None = None
```

- [ ] **Step 2: Verify import is present**

The file already imports `WebSocket` from `fastapi` (line 5) — no additional import needed.

- [ ] **Step 3: Commit**
```bash
cd /Users/victorrentea/workspace/training-assistant
git add railway/shared/state.py
git commit -m "feat: add claude_inbox_ws slot to AppState"
```

---

### Task 2: Create inbox router

**Files:**
- Create: `railway/features/inbox/__init__.py`
- Create: `railway/features/inbox/router.py`

- [ ] **Step 1: Write failing tests first** (see Task 3 — write tests before implementation)

Skip ahead to Task 3, write the tests, watch them fail, then come back here.

- [ ] **Step 2: Create package marker**
```bash
touch railway/features/inbox/__init__.py
```

- [ ] **Step 3: Create `railway/features/inbox/router.py`**

```python
import hmac
import json
import logging
import os

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from railway.shared.state import state

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook/agentmail")
async def agentmail_webhook(request: Request):
    expected = os.environ.get("AGENTMAIL_WEBHOOK_SECRET", "")
    incoming = request.headers.get("x-webhook-secret", "")
    if not expected or not hmac.compare_digest(incoming.encode(), expected.encode()):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    body = await request.json()
    if body.get("event_type") != "message.received":
        return {"ok": True, "ignored": True}

    ws = state.claude_inbox_ws
    if ws is not None:
        try:
            await ws.send_text(json.dumps({"type": "email_received"}))
            logger.info("inbox ↓ forwarded email_received to listener")
        except Exception as exc:
            logger.warning("inbox ↓ listener send failed: %s", exc)
            state.claude_inbox_ws = None
    else:
        logger.warning("inbox: no listener connected — event dropped")

    return {"ok": True}


@router.websocket("/ws/claude-inbox")
async def claude_inbox_ws_endpoint(websocket: WebSocket, token: str = ""):
    expected = os.environ.get("CLAUDE_INBOX_WS_TOKEN", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        await websocket.close(code=4003)
        return

    await websocket.accept()
    state.claude_inbox_ws = websocket
    logger.info("inbox: listener connected")

    try:
        while True:
            await websocket.receive_text()  # keep connection alive; listener sends nothing
    except WebSocketDisconnect:
        logger.info("inbox: listener disconnected")
    finally:
        if state.claude_inbox_ws is websocket:
            state.claude_inbox_ws = None
```

- [ ] **Step 4: Run the tests to verify they pass**
```bash
uv run --extra dev pytest tests/unit/test_inbox_router.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**
```bash
git add railway/features/inbox/
git commit -m "feat: add AgentMail webhook receiver and claude-inbox WebSocket"
```

---

### Task 3: Write unit tests for inbox router

**Files:**
- Create: `tests/unit/test_inbox_router.py`

- [ ] **Step 1: Write tests**

```python
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from railway.features.inbox.router import router
from railway.shared import state as state_module

app = FastAPI()
app.include_router(router)
client = TestClient(app)

GOOD_SECRET = "test-secret-abc"


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("AGENTMAIL_WEBHOOK_SECRET", GOOD_SECRET)
    monkeypatch.setenv("CLAUDE_INBOX_WS_TOKEN", "ws-token-xyz")
    state_module.state.claude_inbox_ws = None


class TestWebhookAuth:
    def test_missing_secret_returns_403(self):
        resp = client.post("/webhook/agentmail", json={"event_type": "message.received"})
        assert resp.status_code == 403

    def test_wrong_secret_returns_403(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": "wrong"},
        )
        assert resp.status_code == 403

    def test_correct_secret_returns_200(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestWebhookForwarding:
    def test_non_message_event_is_ignored(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.sent"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json().get("ignored") is True

    def test_forwards_to_listener_when_connected(self):
        mock_ws = AsyncMock()
        state_module.state.claude_inbox_ws = mock_ws

        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        mock_ws.send_text.assert_called_once_with(json.dumps({"type": "email_received"}))

    def test_no_listener_connected_still_returns_200(self):
        state_module.state.claude_inbox_ws = None
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail** (router not mounted yet in test app — that's OK, test file imports it directly)
```bash
uv run --extra dev pytest tests/unit/test_inbox_router.py -v
```
Expected: ImportError or failures because `railway/features/inbox/router.py` doesn't exist yet.

- [ ] **Step 3: Go implement Task 2, then come back and run tests again**

---

### Task 4: Mount inbox router in `railway/app.py`

**Files:**
- Modify: `railway/app.py`

- [ ] **Step 1: Add import** after the other feature router imports (around line 24):
```python
from railway.features.inbox.router import router as inbox_router
```

- [ ] **Step 2: Mount router** in the root-level routes section (after `app.include_router(ws.router)`, around line 121):
```python
# AgentMail webhook receiver + claude-inbox WebSocket
app.include_router(inbox_router)
```

- [ ] **Step 3: Add env var names to `secrets.env`** (no values — those go in Railway dashboard):
```
# AgentMail webhook integration
AGENTMAIL_WEBHOOK_SECRET=
CLAUDE_INBOX_WS_TOKEN=
```

- [ ] **Step 4: Run full unit test suite to confirm no regressions**
```bash
uv run --extra dev pytest tests/unit/ -v
```
Expected: all PASS

- [ ] **Step 5: Commit**
```bash
git add railway/app.py secrets.env
git commit -m "feat: mount inbox router in Railway app"
```

- [ ] **Step 6: Push to master (triggers Railway deploy)**
```bash
git push origin master
```

---

### Task 5: Create local listener script

**Files:**
- Create: `~/.claude/inbox-ws-listener.py`

- [ ] **Step 1: Write the script**

Create `/Users/victorrentea/.claude/inbox-ws-listener.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["websockets>=13.0"]
# ///
"""AgentMail event-driven Claude inbox listener.

On every connect:
  1. WebSocket opens (future events buffered from now)
  2. Catch-up scan: run Claude to process any missed unread emails
  3. Wait for email_received events → run Claude for each

Reconnects automatically after disconnect.
"""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

import websockets

RAILWAY_WS_URL = "wss://interact.victorrentea.ro/ws/claude-inbox"
WS_TOKEN = os.environ.get("CLAUDE_INBOX_WS_TOKEN", "")
CLAUDE = Path.home() / ".claude/local/claude"
MCP_CONFIG = Path.home() / ".claude/agentmail-mcp-config.json"
LOGFILE = Path.home() / ".claude/inbox-ws.log"

INBOX_PROMPT = """\
Check the Victor Flow AgentMail inbox for unread threads.

Steps:
1. Call list_threads with inbox_id='victor.flux@agentmail.to' and labels=["unread"] to get only unread threads.
2. If the result has no threads: exit silently.
3. For each unread thread:
   a. Call get_thread to read the full thread including all messages.
   b. Check the ORIGINAL sender of the FIRST message in the thread (not later replies). If the original sender's email is NOT exactly victorrentea@gmail.com: call update_message with remove_labels=["UNREAD"] on the latest message to mark it as read, then skip it entirely — no reply, no action.
   c. If the original sender IS victorrentea@gmail.com: parse the task from the subject and body combined.
   d. Execute the task fully (you have full access to ~/workspace).
   e. Call reply_to_message to reply in the same thread with a clear summary of what was done, or a follow-up question if you need clarification.
   f. Call update_message with remove_labels=["UNREAD"] on the latest message to mark it as read.

Working directory is ~/workspace. Only act on emails from victorrentea@gmail.com.\
"""

logging.basicConfig(
    filename=str(LOGFILE),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
logger = logging.getLogger(__name__)


def run_claude():
    logger.info("=== Claude inbox check starting ===")
    result = subprocess.run(
        [str(CLAUDE), "--mcp-config", str(MCP_CONFIG), "--print"],
        input=INBOX_PROMPT,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        logger.info(result.stdout.strip())
    logger.info("=== Claude finished (exit %d) ===", result.returncode)


async def listen():
    url = f"{RAILWAY_WS_URL}?token={WS_TOKEN}"
    logger.info("Connecting to Railway claude-inbox WebSocket...")
    async with websockets.connect(url) as ws:
        logger.info("Connected. Running catch-up scan for missed emails...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_claude)
        logger.info("Catch-up done. Waiting for webhook events...")
        async for raw in ws:
            data = json.loads(raw)
            if data.get("type") == "email_received":
                logger.info("email_received event received")
                await loop.run_in_executor(None, run_claude)


async def main():
    while True:
        try:
            await listen()
        except Exception as exc:
            logger.warning("Connection lost: %s — reconnecting in 10s", exc)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Make it executable**
```bash
chmod +x ~/.claude/inbox-ws-listener.py
```

- [ ] **Step 3: Test it manually** (requires Railway to be deployed and env vars set — do this after Task 6)

---

### Task 6: Generate secrets and configure env vars

- [ ] **Step 1: Generate a strong token for `CLAUDE_INBOX_WS_TOKEN`**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output — this is your `CLAUDE_INBOX_WS_TOKEN`.

- [ ] **Step 2: Generate a strong secret for `AGENTMAIL_WEBHOOK_SECRET`**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output — this is your `AGENTMAIL_WEBHOOK_SECRET`.

- [ ] **Step 3: Add both to `~/.claude/agentmail.env`**

Append to `/Users/victorrentea/.claude/agentmail.env`:
```
CLAUDE_INBOX_WS_TOKEN=<token from step 1>
AGENTMAIL_WEBHOOK_SECRET=<secret from step 2>
```

- [ ] **Step 4: Set both in Railway dashboard**

Go to https://railway.app → your training-assistant project → Variables tab:
- `AGENTMAIL_WEBHOOK_SECRET` = value from step 2
- `CLAUDE_INBOX_WS_TOKEN` = value from step 1

Railway will redeploy automatically.

---

### Task 7: Create new LaunchAgent and migrate

**Files:**
- Create: `~/Library/LaunchAgents/ro.victorrentea.claude-inbox-ws.plist`

- [ ] **Step 1: Create the plist**

Create `/Users/victorrentea/Library/LaunchAgents/ro.victorrentea.claude-inbox-ws.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ro.victorrentea.claude-inbox-ws</string>

    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/uv</string>
        <string>run</string>
        <string>--script</string>
        <string>/Users/victorrentea/.claude/inbox-ws-listener.py</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/victorrentea/.claude/inbox-ws.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/victorrentea/.claude/inbox-ws.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>/Users/victorrentea</string>
        <key>PATH</key>
        <string>/Users/victorrentea/.nvm/versions/node/v22.21.1/bin:/Users/victorrentea/.claude/local:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>CLAUDE_INBOX_WS_TOKEN</key>
        <string>REPLACE_WITH_TOKEN_FROM_TASK_6</string>
    </dict>
</dict>
</plist>
```

Replace `REPLACE_WITH_TOKEN_FROM_TASK_6` with the actual token value from Task 6 Step 1.

- [ ] **Step 2: Unload the old polling LaunchAgent**
```bash
launchctl unload ~/Library/LaunchAgents/com.victorrentea.claude-inbox.plist
```

- [ ] **Step 3: Load the new listener LaunchAgent**
```bash
launchctl load ~/Library/LaunchAgents/ro.victorrentea.claude-inbox-ws.plist
```

- [ ] **Step 4: Verify it started**
```bash
launchctl list | grep claude-inbox-ws
tail -20 ~/.claude/inbox-ws.log
```
Expected: process listed, log shows "Connected" and "Waiting for webhook events..."

---

### Task 8: Register webhook in AgentMail UI

*(Victor does this in the browser — Claude assists)*

- [ ] **Step 1: Open AgentMail webhook settings**

Go to https://app.agentmail.to → Inboxes → `victor.flux@agentmail.to` → Webhooks (or Settings → Webhooks).

- [ ] **Step 2: Add webhook**
- URL: `https://interact.victorrentea.ro/webhook/agentmail`
- Events: `message.received`
- Secret: value of `AGENTMAIL_WEBHOOK_SECRET` from Task 6

- [ ] **Step 3: Smoke test**

Send a test email to `victor.flux@agentmail.to` from `victorrentea@gmail.com`.

Watch:
```bash
tail -f ~/.claude/inbox-ws.log
```
Expected: `email_received event received` → `Claude inbox check starting` → `Claude finished`
