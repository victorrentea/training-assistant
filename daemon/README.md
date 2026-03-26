# Workshop Daemon — Local Setup

Heavy ML dependencies run locally on the trainer's Mac. Never deployed to Railway.

## One-time setup

From the repo root:
```bash
pip install -e daemon/
```

This installs chromadb, sentence-transformers, and other heavy deps into system Python.

## Running

From the repo root:
```bash
python3 training_daemon.py
```

The daemon starts a background indexer thread watching `MATERIALS_FOLDER` for changes,
and polls the server every second for quiz generation requests from the host panel.
It also incrementally normalizes raw transcript lines into daily normalized files:
`YYYY-MM-DD transcription.txt`.

## Manual transcript query

Run only on demand when you need to extract normalized lines from a time range:

```bash
python3 -m daemon.transcript_query 2026-03-25T12:00:00 2026-03-26T09:30:00
```

## Rebuild normalized transcripts

Reset offsets and rebuild normalized files from raw transcripts:

```bash
python3 -m daemon.rebuild_normalized_transcripts --from-iso 2026-03-24T09:30:00
```

The command creates a backup folder in `TRANSCRIPTION_FOLDER` before deleting/rebuilding:
`.backup-normalized-YYYYMMDD-HHMMSS`.

## Configuration (in secrets.env)

```
MATERIALS_FOLDER=/path/to/materials  # default: materials/ in repo root
TRANSCRIPTION_FOLDER=/Users/yourname/Documents/transcriptions  # must exist, can be empty
ANTHROPIC_API_KEY=sk-ant-...
WORKSHOP_SERVER_URL=https://interact.victorrentea.ro
HOST_USERNAME=host
HOST_PASSWORD=...
```

## First indexing

On first run, all materials are indexed. With `all-mpnet-base-v2` on CPU, expect 15–30 min
for 150MB of PDFs. During this window, topic-mode generation falls back to Claude's general
knowledge. Subsequent runs only re-index changed files (seconds).

## Supported formats

`.pdf`, `.epub`, `.mobi`, `.txt`, `.md`, `.html`

## ChromaDB index location

`~/.workshop-rag/chroma/` — local only, not in git.
