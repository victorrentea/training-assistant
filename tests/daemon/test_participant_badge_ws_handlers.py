"""Guard: the participant page must handle every badge/counter WS message the
daemon broadcasts to participants.

Regression for the Past Slides badge live-update, which silently never fired
because the daemon broadcast `slides_history_updated` while participant.html
listened for `slides_history_count_updated`. These messages are rendered
directly by the participant WS switch (nav badges / counters); other participant
messages (wordcloud/qa/codereview/debate/…) are reconciled via a full `state`
refetch and are intentionally out of scope here.
"""
from pathlib import Path

from daemon.ws_messages import PARTICIPANT_MESSAGES

PARTICIPANT_HTML = Path(__file__).parent.parent.parent / "static" / "participant.html"

# WS messages whose only effect is to update a participant nav badge / counter
# directly in the WS switch. Each MUST have a matching `case '<type>'` handler.
BADGE_MESSAGE_TYPES = [
    "notes_updated",
    "summary_updated",
    "agenda_updated",
    "slides_history_updated",
    "files_count_updated",
    "active_participants_count_updated",
]


def test_badge_messages_are_registered():
    for name in BADGE_MESSAGE_TYPES:
        assert name in PARTICIPANT_MESSAGES, (
            f"{name} is not a registered participant WS message"
        )


def test_participant_html_handles_each_badge_message():
    html = PARTICIPANT_HTML.read_text(encoding="utf-8")
    missing = [name for name in BADGE_MESSAGE_TYPES if f"case '{name}'" not in html]
    assert not missing, (
        "participant.html WS switch is missing case handler(s) for: "
        + ", ".join(missing)
        + " — these daemon broadcasts would silently never update the UI."
    )
