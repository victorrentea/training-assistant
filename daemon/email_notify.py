"""Email notifications via AgentMail.

Sends notifications to NOTIFY_EMAIL using the AgentMail API.
Requires AGENTMAIL_API_KEY and NOTIFY_EMAIL in secrets env.
Failures are logged but never raise — notifications are best-effort.
"""

import os
from daemon import log

_INBOX_ID = "claude-victor-dispatch@agentmail.to"

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


def notify(subject: str, body: str) -> None:
    """Send a notification email. Best-effort — never raises."""
    to = os.environ.get("NOTIFY_EMAIL")
    if not to:
        return
    client = _get_client()
    if not client:
        return
    try:
        client.inboxes.messages.send(
            _INBOX_ID,
            to=[to],
            subject=subject,
            text=body,
        )
        log.info("email", f"Sent: {subject!r} → {to}")
    except Exception as e:
        log.error("email", f"Failed to send '{subject}': {e}")
