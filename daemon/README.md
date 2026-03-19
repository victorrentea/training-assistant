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
python3 quiz_daemon.py
```

The daemon starts a background indexer thread watching `MATERIALS_FOLDER` for changes,
and polls the server every second for quiz generation requests from the host panel.

## Configuration (in secrets.env)

```
MATERIALS_FOLDER=/Users/yourname/Documents/materials
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
