"""
Minimal mock daemon: connects to the backend via WebSocket and responds
to session_request messages with global_state_saved acks.

This is the simplest possible daemon mock — enough for the
"host starts session → participant joins" flow.
"""

import asyncio
import json
import os
import base64
import websockets


BACKEND_HOST = os.environ.get("BACKEND_HOST", "localhost")
BACKEND_PORT = os.environ.get("BACKEND_PORT", "8000")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


async def run_mock_daemon():
    url = f"ws://{BACKEND_HOST}:{BACKEND_PORT}/ws/daemon"
    creds = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}

    print(f"[mock-daemon] Connecting to {url}")
    async with websockets.connect(url, additional_headers=headers) as ws:
        print("[mock-daemon] Connected!")
        async for raw in ws:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")
            print(f"[mock-daemon] Received: {msg_type}")

            if msg_type == "session_request":
                request_id = msg.get("request_id", "")
                # Ack the session request so backend doesn't hang
                ack = {"type": "global_state_saved", "request_id": request_id}
                await ws.send(json.dumps(ack))
                print(f"[mock-daemon] Sent global_state_saved ack for request_id={request_id}")

                # Also send session_sync with active session
                action = msg.get("action", "")
                name = msg.get("name", "")
                if action in ("start", "create"):
                    sync = {
                        "type": "session_sync",
                        "main": {
                            "name": name,
                            "status": "active",
                            "start_time": "2026-03-29T10:00:00Z",
                        },
                    }
                    await ws.send(json.dumps(sync))
                    print(f"[mock-daemon] Sent session_sync for '{name}'")

            elif msg_type == "kicked":
                print("[mock-daemon] Kicked by backend, exiting")
                break
            else:
                # Ignore other messages (state_snapshot, session_snapshot, etc.)
                pass


if __name__ == "__main__":
    asyncio.run(run_mock_daemon())
