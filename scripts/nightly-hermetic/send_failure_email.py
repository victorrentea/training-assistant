#!/usr/bin/env python3
"""Email a hermetic-test-failure summary via AgentMail.

Usage: send_failure_email.py <reason> <log_path>
Reads AGENTMAIL_API_KEY from env. Tails last 200 log lines into the body.
"""
import json
import os
import sys
import urllib.error
import urllib.request

INBOX = "claude-victor-dispatch@agentmail.to"
TO = "victorrentea@gmail.com"
TAIL_LINES = 200


def main() -> int:
    api_key = os.environ.get("AGENTMAIL_API_KEY", "").strip()
    if not api_key:
        print("AGENTMAIL_API_KEY not set", file=sys.stderr)
        return 1

    reason = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    log_path = sys.argv[2] if len(sys.argv) > 2 else ""

    tail = ""
    if log_path and os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-TAIL_LINES:])

    body = (
        f"Reason: {reason}\n\n"
        f"Full log on Mac: {log_path}\n\n"
        "Reply to this email with a short instruction (e.g. 'fix it') to "
        "trigger a Claude Code session against this failure.\n\n"
        f"------ last {TAIL_LINES} log lines ------\n{tail}\n"
    )
    payload = {
        "to": TO,
        "subject": f"\u274c Nightly hermetic failed: {reason}",
        "text": body,
    }
    url = f"https://api.agentmail.to/v0/inboxes/{INBOX}/messages/send"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"AgentMail responded {resp.status}")
            print(resp.read().decode("utf-8", errors="replace"))
        return 0
    except urllib.error.HTTPError as exc:
        print(f"AgentMail HTTPError {exc.code}: {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"AgentMail send failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
