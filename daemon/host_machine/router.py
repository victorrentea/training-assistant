"""Host-machine privilege endpoints — reachable only over loopback.

This router is deliberately NOT mounted under /api/participant/*. That prefix is
the only one Railway forwards to the daemon (railway/features/ws/proxy_bridge.py
`participant_proxy`), so everything here is unreachable from the internet by
construction. Combined with the loopback bind, the Host-header guard and the
CORS allowlist in daemon/host_server.py, "can this browser reach 127.0.0.1:1234
on the trainer's machine?" IS the security boundary.

That is the whole model, and it is why the endpoint needs no token: nothing
secret travels through Railway, so there is nothing to intercept or replay. Do
not "harden" this with a shared secret — moving the grant onto a
network-visible path is what would weaken it.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from daemon.participant.sanitize import RESERVED_TRAINER_NAME
from daemon.participant.state import participant_state

router = APIRouter(prefix="/api/host-machine", tags=["host-machine"])


class ClaimTrainerRequest(BaseModel):
    participant_id: str


class ClaimTrainerResponse(BaseModel):
    granted: bool
    display_name: str


@router.post("/claim-trainer", response_model=ClaimTrainerResponse)
async def claim_trainer(body: ClaimTrainerRequest) -> ClaimTrainerResponse:
    """Grant the trainer identity to a UUID running on this machine.

    Registration arrives over a different path (browser -> Railway -> WS ->
    daemon) than this loopback call, so the two race. Both orders must work:
    this handler renames an already-registered UUID, and register consults
    trainer_pids for a UUID that claimed first.
    """
    ps = participant_state
    ps.trainer_pids.add(body.participant_id)

    if body.participant_id in ps.participant_names:
        ps.participant_names[body.participant_id] = RESERVED_TRAINER_NAME
        ps.anonymous_pids.discard(body.participant_id)
        # Deferred import: participant.router imports heavy identity helpers.
        from daemon.participant.router import _notify_host_participant_list

        await _notify_host_participant_list()

    ps.persist()
    return ClaimTrainerResponse(granted=True, display_name=RESERVED_TRAINER_NAME)
