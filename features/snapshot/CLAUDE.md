# Snapshot

## Purpose
Diagnostic endpoints for serializing and restoring the full AppState as a JSON blob. Used for daemon-based persistence (the daemon polls the snapshot and writes it to disk; on server restart the daemon posts it back).

## Endpoints
- `GET /api/state-snapshot` — serialize all persistent AppState fields to JSON + MD5 hash
- `POST /api/state-restore` — restore state from a snapshot dict; broadcasts updated state to all clients

## State Fields
This feature reads/writes virtually all `AppState` fields. It is the canonical serialization layer for cross-restart persistence. Key conversions:
- Python `set` → sorted `list` on serialize; `list` → `set` on restore
- `datetime` → ISO string on serialize; ISO string → `datetime` on restore
- Special PIDs (`__host__`, `__overlay__`) are excluded from participant maps on serialize

## Design Decisions
- The MD5 hash allows the daemon to detect whether state has changed since the last snapshot (skip redundant writes).
- `needs_restore: bool` flag is set to `False` after a successful restore.
- This router is separate from `features/session` to keep diagnostic/low-level serialization decoupled from business session lifecycle logic.
- `POST /api/state-restore` calls `broadcast_state()` after restoring so all connected clients see the restored state immediately.
- Special participant IDs (`__host__`, `__overlay__`) are not persisted; they re-register on WebSocket reconnect.
