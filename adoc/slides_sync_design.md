# Slides Sync Design (Host -> Backend Mirror)

## Goal
Keep backend slide storage an exact mirror of host-generated PDFs, so participant slides work even when backend runs on a different machine/cloud runtime.

## Fixed Host Paths
- Host materials root (hardcoded): `/Users/victorrentea/workspace/training-assistant/materials`
- Host slides folder (generated PDFs): `/Users/victorrentea/workspace/training-assistant/materials/slides`

## Source of Truth
- PPTX source files remain on host machine.
- Generated PDFs on host are the canonical artifact set.
- Backend mirror folder must contain the same PDF set (add/update/delete parity).

## Target Components
- Slides Daemon (host machine): detects PPTX changes, regenerates PDFs, computes catalog diff.
- Slides Sync API (backend FastAPI): authenticated endpoints for upload/delete/list.
- Backend Slides Storage (cloud machine): local directory used by `/api/slides` and `/api/slides/file/{slug}`.
- Participant UI: reads merged catalog from backend, renders selected PDF.

## Sync Contract
1. Daemon regenerates changed PPTX into host slides folder.
2. Daemon computes remote diff against backend catalog.
3. Daemon uploads new/updated PDFs to backend.
4. Daemon sends delete requests for PDFs removed on host.
5. Backend updates its local slides storage.
6. Backend exposes synchronized catalog to participants.

## Backend Requirements
- Add authenticated binary upload endpoint for a PDF file + metadata (slug/name/updated_at).
- Add authenticated delete endpoint by slug.
- Ensure backend catalog/list endpoint reflects only files present in backend storage.
- Keep `/api/slides` public and stable for participant UI.

## Consistency Rules
- Filename/slug normalization must be deterministic and collision-safe.
- Delete propagation is mandatory (host deletion removes backend file).
- Sync is idempotent and safe to retry.
- Partial failures are retried on next daemon cycle.

## Observability
- Daemon logs sync summary per cycle: uploaded, updated, deleted, skipped.
- Backend logs slide file operations and auth failures.

## Non-goals
- No direct host filesystem access from backend.
- No manual host UI upload flow.
