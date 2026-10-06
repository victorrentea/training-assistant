"""Throttled roster fan-out, so the daemon holds up when a conference talk fills.

At a talk, 400-500 people can join within a minute or two. The active count
(``active_participants_count_updated``) used to go to EVERY participant through
Railway on every presence change, which is O(N²) deliveries for N joins.

It now goes through a LoopThrottle: at most one broadcast per interval, leading
and trailing edge. The count is computed from live state when it is sent, so the
final count always goes out. The message contract is unchanged.
"""
from daemon.participant.state import participant_state
from daemon.throttle import LoopThrottle
from daemon.ws_messages import ActiveParticipantsCountUpdatedMsg
from daemon.ws_publish import broadcast

ACTIVE_COUNT_INTERVAL_S = 1.0


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


active_count = LoopThrottle("active-count", ACTIVE_COUNT_INTERVAL_S, _broadcast_active_count)


def request_active_count_broadcast() -> None:
    """Throttled active-count broadcast, callable from any thread.

    Before the daemon loop is up (daemon startup) it sends right away, unthrottled,
    so the count Railway pushes on connect is never dropped.
    """
    if not active_count.request_threadsafe():
        broadcast_active_count()
