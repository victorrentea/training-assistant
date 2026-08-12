"""Email notifications via AgentMail.

Sends notifications to NOTIFY_EMAIL using the AgentMail API.
Requires AGENTMAIL_API_KEY and NOTIFY_EMAIL in secrets env.
Failures are logged but never raise — notifications are best-effort.

SECURITY: the recipient comes from the environment and the sending inbox from a
fixed allowlist of module constants. Neither is ever taken from a request, so no
caller — participant included — can turn this into an open relay. Subject lines
are sanitised (see ``_header_safe``) because a bare newline in a subject is an
SMTP header-injection primitive.
"""

import os

from daemon import log

_INBOX_ID = "claude-victor-dispatch@agentmail.to"
#: Participant-originated mail (bug reports) is sent from Victor's own relay
#: inbox so replies land where he reads them.
PARTICIPANT_INBOX_ID = "victor.flux@agentmail.to"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("AGENTMAIL_API_KEY")
    if not api_key:
        return None
    try:
        from agentmail import AgentMail
        _client = AgentMail(api_key=api_key)
    except Exception as e:
        log.error("email", f"Failed to init AgentMail client: {e}")
    return _client


def _header_safe(value: str, limit: int = 120) -> str:
    """Collapse a string into something safe to splice into a mail header.

    Drops CR/LF and every other control character — a newline in a subject lets
    an attacker append arbitrary headers (Bcc:, Content-Type:, …) — then trims to
    ``limit`` so a long paste cannot bloat the header.
    """
    cleaned = "".join(ch for ch in value if ch.isprintable())
    return cleaned[:limit].strip()


def notify(subject: str, body: str, from_inbox: str = _INBOX_ID) -> bool:
    """Send a notification email. Best-effort — never raises.

    Returns True only when AgentMail accepted the message, so callers can tell a
    participant "this did not reach Victor" instead of a false confirmation.
    """
    to = os.environ.get("NOTIFY_EMAIL")
    if not to:
        return False
    client = _get_client()
    if not client:
        return False
    try:
        client.inboxes.messages.send(
            from_inbox,
            to=[to],
            subject=_header_safe(subject),
            text=body,
        )
        log.info("email", f"Sent: {subject!r} → {to}")
        return True
    except Exception as e:
        log.error("email", f"Failed to send '{subject}': {e}")
        return False
