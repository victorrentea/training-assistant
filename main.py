"""
Workshop Live Interaction Tool
FastAPI + WebSocket backend
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import json
import asyncio
import logging
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Workshop Tool")

# ---------------------------------------------------------------------------
# In-memory state  (single active room model)
# ---------------------------------------------------------------------------

LOTR_NAMES = [
    "Frodo", "Samwise", "Gandalf", "Aragorn", "Legolas", "Gimli", "Boromir",
    "Merry", "Pippin", "Galadriel", "Elrond", "Saruman", "Faramir",
    "Eowyn", "Theoden", "Treebeard", "Bilbo", "Thorin", "Smaug", "Gollum",
    "Radagast", "Tom Bombadil", "Glorfindel", "Celeborn", "Arwen", "Eomer",
    "Haldir", "Shadowfax", "Grima Wormtongue",
]

class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.poll: Optional[dict] = None          # current poll definition
        self.poll_active: bool = False             # is voting open?
        self.votes: dict[str, str] = {}            # participant_name -> option_id
        self.participants: dict[str, WebSocket] = {}  # name -> ws
        self.suggested_names: set[str] = set()     # names handed out but not yet connected
        self.locations: dict[str, str] = {}        # participant_name -> location string

    def suggest_name(self) -> str:
        taken = set(self.participants.keys()) | self.suggested_names
        available = [n for n in LOTR_NAMES if n not in taken]
        name = random.choice(available) if available else f"Guest{random.randint(100, 999)}"
        self.suggested_names.add(name)
        return name

    def vote_counts(self) -> dict:
        if not self.poll:
            return {}
        counts = {opt["id"]: 0 for opt in self.poll["options"]}
        for selection in self.votes.values():
            # selection is a list for multi polls, a string for single polls
            ids = selection if isinstance(selection, list) else [selection]
            for option_id in ids:
                if option_id in counts:
                    counts[option_id] += 1
        return counts

state = AppState()

# ---------------------------------------------------------------------------
# Pydantic models for REST endpoints
# ---------------------------------------------------------------------------

class PollCreate(BaseModel):
    question: str
    options: list[str]          # list of option texts
    multi: bool = False         # allow multiple selections per participant

class PollOpen(BaseModel):
    open: bool                  # True = open voting, False = close voting

# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send a message to all connected participants."""
    dead = []
    for name, ws in state.participants.items():
        if name == exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(name)
    for name in dead:
        state.participants.pop(name, None)

async def send_state_to(ws: WebSocket):
    """Send the full current state to a single newly connected participant."""
    await ws.send_text(json.dumps(build_state_message()))

def participant_names() -> list[str]:
    return sorted(n for n in state.participants if n != "__host__")

def build_state_message() -> dict:
    names = participant_names()
    return {
        "type": "state",
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "participant_count": len(names),
        "participant_names": names,
        "participant_locations": {n: state.locations.get(n, "") for n in names},
    }

# ---------------------------------------------------------------------------
# WebSocket endpoint  — participants connect here
# ---------------------------------------------------------------------------

@app.websocket("/ws/{participant_name}")
async def websocket_endpoint(websocket: WebSocket, participant_name: str):
    name = participant_name.strip()
    if not name:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    state.participants[name] = websocket
    state.suggested_names.discard(name)
    logger.info(f"Connected: {name} ({len(state.participants)} total)")

    # Send current state immediately on join
    await send_state_to(websocket)

    # Notify everyone of the new participant count
    names = participant_names()
    await broadcast({"type": "participant_count", "count": len(names), "names": names})

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "location":
                loc = str(data.get("location", "")).strip()[:80]
                if loc:
                    state.locations[name] = loc
                    names = participant_names()
                    await broadcast({
                        "type": "participant_count",
                        "count": len(names),
                        "names": names,
                        "locations": {n: state.locations.get(n, "") for n in names},
                    })

            elif data.get("type") == "vote":
                option_id = data.get("option_id")
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                if state.poll_active and state.poll and option_id in valid_ids:
                    state.votes[name] = option_id
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

            elif data.get("type") == "multi_vote":
                option_ids = data.get("option_ids", [])
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                if (
                    state.poll_active
                    and state.poll
                    and state.poll.get("multi")
                    and isinstance(option_ids, list)
                    and all(oid in valid_ids for oid in option_ids)
                ):
                    state.votes[name] = option_ids
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

    except WebSocketDisconnect:
        state.participants.pop(name, None)
        state.locations.pop(name, None)
        logger.info(f"Disconnected: {name} ({len(state.participants)} remaining)")
        names = participant_names()
        await broadcast({
            "type": "participant_count",
            "count": len(names),
            "names": names,
            "locations": {n: state.locations.get(n, "") for n in names},
        })

# ---------------------------------------------------------------------------
# Host REST API  (no auth in this scaffold — add a secret header later)
# ---------------------------------------------------------------------------

@app.post("/api/poll")
async def create_poll(poll: PollCreate):
    """Create a new poll (replaces any existing one, resets votes)."""
    if not poll.question.strip():
        raise HTTPException(400, "Question cannot be empty")
    if len(poll.options) < 2:
        raise HTTPException(400, "Need at least 2 options")
    if len(poll.options) > 8:
        raise HTTPException(400, "Maximum 8 options")

    state.poll = {
        "question": poll.question.strip(),
        "multi": poll.multi,
        "options": [
            {"id": f"opt{i}", "text": opt.strip()}
            for i, opt in enumerate(poll.options)
            if opt.strip()
        ],
    }
    state.poll_active = False
    state.votes = {}

    await broadcast(build_state_message())
    return {"ok": True, "poll": state.poll}


@app.post("/api/poll/status")
async def set_poll_status(body: PollOpen):
    """Open or close voting on the current poll."""
    if not state.poll:
        raise HTTPException(400, "No poll created yet")
    state.poll_active = body.open
    await broadcast(build_state_message())
    return {"ok": True, "poll_active": state.poll_active}


@app.delete("/api/poll")
async def clear_poll():
    """Remove the current poll entirely."""
    state.poll = None
    state.poll_active = False
    state.votes = {}
    await broadcast(build_state_message())
    return {"ok": True}


@app.get("/api/suggest-name")
async def suggest_name():
    return {"name": state.suggest_name()}


@app.get("/api/status")
async def status():
    return {
        "participants": len(state.participants),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "total_votes": len(state.votes),
    }

# ---------------------------------------------------------------------------
# Serve static files & pages
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def participant_page():
    return FileResponse("static/participant.html")

@app.get("/host", response_class=HTMLResponse)
async def host_page():
    return FileResponse("static/host.html")
