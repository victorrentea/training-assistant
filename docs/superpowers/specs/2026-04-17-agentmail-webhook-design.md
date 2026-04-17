# AgentMail Webhook via Railway — Design

**Date:** 2026-04-17
**Goal:** Eliminate polling-based Claude inbox checks. Replace the 5-minute LaunchAgent cron with an event-driven flow: AgentMail pushes a webhook to Railway, Railway forwards it via WebSocket to a lightweight listener on the Mac, the listener triggers Claude only when a real email arrives.

---

## Problem

`scripts/claude-inbox-check.sh` runs every 5 minutes via a LaunchAgent, spawning Claude unconditionally. On days with no incoming mail, this burns tokens for nothing. The fix is to flip to push: zero cost when idle, instant reaction when mail arrives.

---

## Architecture

```
AgentMail ──POST /webhook/agentmail──▶ Railway (interact.victorrentea.ro)
                                            │
                               wss://.../ws/claude-inbox
                                            │
                                  ~/.claude/inbox-ws-listener.py  (LaunchAgent, Mac)
                                            │
                                  claude --print  (only when email arrives)
```

### Components

| Component | Location | Responsibility |
|---|---|---|
| `POST /webhook/agentmail` | `railway/features/inbox/router.py` | Receive AgentMail event, verify secret, forward to connected listener |
| `GET /ws/claude-inbox` | same router | Persistent WebSocket for the local listener |
| `AppState.claude_inbox_ws` | `railway/shared/state.py` | Hold the single active listener WebSocket reference |
| `~/.claude/inbox-ws-listener.py` | Mac local | Connect to Railway WS, on event trigger Claude, auto-reconnect |
| LaunchAgent plist | `~/Library/LaunchAgents/` | Keep listener running at login |

---

## Railway Side

### New router: `railway/features/inbox/router.py`

**`POST /webhook/agentmail`**
- Reads `X-Webhook-Secret` header, compares with `AGENTMAIL_WEBHOOK_SECRET` env var (constant-time compare)
- Returns `403` on mismatch
- Filters to `event_type == "message.received"` only; ignores others silently
- If `AppState.claude_inbox_ws` is set and open, sends JSON `{"type": "email_received"}` to it
- Returns `200 OK` always (AgentMail won't retry on 200)

**`GET /ws/claude-inbox`**
- Accepts `?token=<CLAUDE_INBOX_WS_TOKEN>` query param for auth; closes with `4003` if missing or wrong
- Only one connection at a time: stores ref in `AppState.claude_inbox_ws`, replaces previous if reconnected
- Stays open until disconnect; no heartbeat needed (listener handles reconnect)

### State changes: `railway/shared/state.py`

Add one field:
```python
claude_inbox_ws: WebSocket | None = None
```

### App mount: `railway/app.py`

```python
from railway.features.inbox.router import router as inbox_router
app.include_router(inbox_router)
```

### New env vars (Railway dashboard + `secrets.env`)

| Var | Purpose |
|---|---|
| `AGENTMAIL_WEBHOOK_SECRET` | AgentMail signs outgoing webhooks with this |
| `CLAUDE_INBOX_WS_TOKEN` | Local listener authenticates with this |

---

## Local Listener: `~/.claude/inbox-ws-listener.py`

### Startup sequence (on every connect / reconnect)

```
1. Connect WebSocket to wss://interact.victorrentea.ro/ws/claude-inbox?token=<TOKEN>
        ↓  (WS open — future events are now captured)
2. Call AgentMail API: list_threads(inbox_id, labels=["unread"])
3. For each unread thread (sequentially, one at a time):
       run_claude(thread)   ← blocks until Claude finishes
4. Enter receive loop — wait for {"type": "email_received"} messages
        ↓
5. On event: run_claude()   ← blocks; queues naturally if emails come fast
```

Step 1 comes before the catch-up scan (step 2) so that emails arriving during catch-up are not lost — they are queued in the WS receive buffer and processed after the scan finishes.

### Responsibilities

- Authenticate with `?token=<CLAUDE_INBOX_WS_TOKEN>` query param (TLS only)
- On each `email_received` event: run `~/.claude/local/claude --mcp-config ... --print` with the inbox prompt (same prompt as current `claude-inbox-check.sh`)
- Process emails sequentially — no parallel Claude invocations
- On disconnect: wait 10 s, reconnect and redo startup sequence (catches missed emails during downtime)
- Log to `~/.claude/inbox-ws.log`

The script is self-contained (~80 lines Python, stdlib + `websockets` package).

### LaunchAgent: `~/Library/LaunchAgents/ro.victorrentea.claude-inbox-ws.plist`

- `RunAtLoad = true`, `KeepAlive = true`
- Replaces the existing 5-minute polling plist
- Exports `AGENTMAIL_WS_TOKEN` from env or reads from `~/.claude/agentmail.env`

---

## AgentMail Registration

In the AgentMail web UI:
- Webhook URL: `https://interact.victorrentea.ro/webhook/agentmail`
- Events: `message.received`
- Secret: value of `AGENTMAIL_WEBHOOK_SECRET`

---

## Security

- Webhook secret verified server-side with `hmac.compare_digest` (timing-safe)
- WebSocket token passed as query param over TLS only (never in logs)
- No business logic executes before both checks pass

---

## Error Cases

| Scenario | Behavior |
|---|---|
| Listener not connected when email arrives | Railway logs warning, returns 200 to AgentMail (event lost — acceptable, AgentMail doesn't queue) |
| Railway redeployed | Listener reconnects within 10 s automatically |
| Mac asleep / offline | On wake, listener reconnects and immediately scans AgentMail for all unread threads, processes them sequentially before entering WS receive loop |
| Multiple emails rapid-fire | Each webhook fires Claude independently; Claude serializes via `--print` blocking call |

---

## Migration

1. Deploy Railway changes
2. Register webhook in AgentMail UI
3. Install listener script + new LaunchAgent
4. Unload and delete old polling LaunchAgent (`ro.victorrentea.claude-inbox`)
