"""A privileged route under /api/participant/* would be world-reachable.

railway/features/ws/proxy_bridge.py forwards /api/participant/{path:path} to the
daemon over the WS bridge. Anything mounted under that prefix is on the public
internet. The host-machine router grants trainer identity with NO authentication
precisely because it is loopback-only — if it ever drifted under that prefix,
any participant could claim the trainer identity with a single POST.

This test is the tripwire for that refactor.
"""
from daemon.host_machine.router import router as host_machine_router

PUBLICLY_FORWARDED_PREFIX = "/api/participant"


def test_host_machine_routes_are_not_publicly_forwarded():
    offenders = [
        route.path
        for route in host_machine_router.routes
        if getattr(route, "path", "").startswith(PUBLICLY_FORWARDED_PREFIX)
    ]
    assert offenders == [], (
        f"Privileged host-machine routes exposed via the Railway proxy: {offenders}"
    )


def test_claim_trainer_is_mounted_where_we_think():
    paths = {getattr(route, "path", "") for route in host_machine_router.routes}
    assert "/api/host-machine/claim-trainer" in paths


def test_railway_only_forwards_the_participant_prefix():
    """Pins the assumption the whole design rests on.

    If Railway ever gains a second catch-all into the daemon, the loopback-only
    guarantee is void and this test should fail loudly.
    """
    from railway.features.ws.proxy_bridge import participant_proxy_router

    forwarded = {getattr(route, "path", "") for route in participant_proxy_router.routes}
    assert forwarded == {"/api/participant/{path:path}"}
