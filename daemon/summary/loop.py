"""Summary polling loop helpers.

Key-points I/O is provided by session_state; this module re-exports for convenience
and provides the run_summary_cycle() helper used by the main orchestrator loop.
"""

from datetime import date
from pathlib import Path

from daemon import log
from daemon.session_state import (
    load_key_points,
    save_key_points,
    save_daemon_state,
    stack_to_daemon_state,
    sync_session_to_server,
    session_start_date,
)
from daemon.summary.summarizer import generate_summary

__all__ = [
    "load_key_points",
    "save_key_points",
    "run_summary_cycle",
]


def run_summary_cycle(
    config,
    session_stack: list[dict],
    sessions_root: Path,
    current_key_points: list[dict],
    summary_watermark: int,
) -> tuple[list[dict], int]:
    """Run one on-demand summary generation cycle.

    Returns updated (current_key_points, summary_watermark).
    Saves key points to disk and syncs to server on success.
    """
    if not session_stack:
        return current_key_points, summary_watermark

    current_session = session_stack[-1]
    session_folder = sessions_root / current_session["name"]
    s_date = session_start_date(current_session)
    incremental = summary_watermark > 0 and bool(current_key_points)

    try:
        result = generate_summary(
            config,
            existing_points=current_key_points if incremental else None,
            since_entry=summary_watermark if incremental else 0,
            session_start_date=s_date,
            course_title=current_session.get("name"),
        )
        if result is not None:
            new_pts = result["new"]
            summary_watermark = result["watermark"]
            if incremental:
                current_key_points = current_key_points + new_pts
            else:
                current_key_points = new_pts
            save_key_points(session_folder, current_key_points, summary_watermark, s_date)
            save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))
            sync_session_to_server(config, session_stack, current_key_points)
            log.info("summarizer", f"Key points: {len(current_key_points)} total (+{len(new_pts)} new)")
    except Exception as e:
        log.error("summarizer", f"Error: {e}")

    return current_key_points, summary_watermark
