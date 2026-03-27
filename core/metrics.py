"""Prometheus custom metrics for the Workshop Tool."""

from prometheus_client import Counter, Gauge, Histogram

# WebSocket connections (host, overlay, participant)
ws_connections_active = Gauge(
    "ws_connections_active",
    "Currently open WebSocket connections",
    ["role"],
)

# All WebSocket messages by type
ws_messages_total = Counter(
    "ws_messages_total",
    "Total WebSocket messages received",
    ["type"],
)

# Poll voting
poll_votes_total = Counter(
    "poll_votes_total",
    "Total votes cast",
)

poll_vote_duration_seconds = Histogram(
    "poll_vote_duration_seconds",
    "Time from poll open to participant vote",
    buckets=[1, 2, 5, 10, 15, 30, 60, 120, 300],
)

# Q&A
qa_questions_total = Counter(
    "qa_questions_total",
    "Total Q&A questions submitted",
)

qa_upvotes_total = Counter(
    "qa_upvotes_total",
    "Total Q&A upvotes given",
)
