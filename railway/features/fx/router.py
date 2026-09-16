"""Public relay for the secret FX link.

A path prefix and nothing else: no token is checked here, no tile is known
here, no state is kept here. The daemon on the trainer's Mac owns all of it,
and this backend stays the dumb proxy it is everywhere else.

The path IS constrained, though. `proxy_to_daemon` hands the string to an httpx
call at the far end, where `../` is resolved against the daemon's own base URL —
so the alphabet is pinned here, before the string can travel.
"""
import re

from fastapi import APIRouter, HTTPException, Request

from railway.features.ws.proxy_bridge import proxy_to_daemon

fx_router = APIRouter()

# The FX token's alphabet plus the two subpaths that hang off it. Anything
# else — uppercase, dots, percent-escapes, slashes beyond one level — is not a
# link this feature ever minted.
_FX_PATH = re.compile(r"^[a-z0-9]{1,24}(/(info|fire|image))?$")


@fx_router.api_route("/fx/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def fx_relay(request: Request, path: str):
    """Relay /fx/* to the daemon's /api/participant/fx/*."""
    if not _FX_PATH.match(path):
        raise HTTPException(status_code=404)
    return await proxy_to_daemon(
        method=request.method,
        path=f"/api/participant/fx/{path}",
        body=await request.body(),
        headers=dict(request.headers),
        participant_id=None,
    )
