"""Throttled roster fan-out, so the daemon holds up when a conference talk fills.

At a talk, 400-500 people can join within a minute or two. Two aggregates used
to be re-sent on every single roster event:

* the host roster (``participant_list_updated``, about 200-600 B per participant,
  100-300 KB at 500) went to the trainer's browser, and host.js re-renders the
  whole list each time. That happened on every register, rename, location
  change, presence change and 30 s activity heartbeat, on the laptop that is
  presenting;
* the active count (``active_participants_count_updated``) went to EVERY
  participant through Railway on every presence change.

Both now go through a LoopThrottle: at most one push per interval, leading and
trailing edge. Each push is built from live state when it is sent, so the final
state always goes out. The message contracts are unchanged.
"""
from daemon.host_state_router import _build_host_participants_list
from daemon.participant.state import participant_state
from daemon.throttle import LoopThrottle
from daemon.ws_messages import ActiveParticipantsCountUpdatedMsg, ParticipantListUpdatedMsg
from daemon.ws_publish import broadcast, notify_host

HOST_ROSTER_INTERVAL_S = 1.0
ACTIVE_COUNT_INTERVAL_S = 1.0


async def _push_host_roster() -> None:
    await notify_host(ParticipantListUpdatedMsg(participants=_build_host_participants_list()))


def active_participant_count() -> int:
    """Online participants that have a name (registered), excluding internal ``__`` ids."""
    ps = participant_state
    # tuple() copies the set in a single C call. The main thread adds to it on
    # presence events while this runs on the event loop, and iterating the live
    # set could raise "Set changed size during iteration".
    online = tuple(ps.online_participants)
    return sum(1 for p in online if not p.startswith("__") and p in ps.participant_names)


def broadcast_active_count() -> None:
    broadcast(ActiveParticipantsCountUpdatedMsg(count=active_participant_count()))


async def _broadcast_active_count() -> None:
    broadcast_active_count()


host_roster = LoopThrottle("host-roster", HOST_ROSTER_INTERVAL_S, _push_host_roster)
active_count = LoopThrottle("active-count", ACTIVE_COUNT_INTERVAL_S, _broadcast_active_count)


def request_active_count_broadcast() -> None:
    """Throttled active-count broadcast, callable from any thread.

    Before the daemon loop is up (daemon startup) it sends right away, unthrottled,
    so the count Railway pushes on connect is never dropped.
    """
    if not active_count.request_threadsafe():
        broadcast_active_count()


def handle_participant_presence(data: dict) -> None:
    """Railway ``participant_presence`` handler. Runs on the daemon main thread
    (``ws_client.drain_queue``), not on the event loop."""
    from daemon.participant.router import _apply_browser_tz

    pid = str(data.get("uuid", "")).strip()
    if not pid or pid.startswith("__"):
        return

    if bool(data.get("online")):
        participant_state.online_participants.add(pid)
        _apply_browser_tz(pid, data.get("tz"))
    else:
        participant_state.online_participants.discard(pid)
    host_roster.request_threadsafe()
    request_active_count_broadcast()
