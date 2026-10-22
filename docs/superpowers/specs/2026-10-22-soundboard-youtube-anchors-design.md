# Soundboard clips on YouTube, as emotional anchors in the summary and wiki

Date: 2026-10-22. Requested by Victor (dictated); he opted out of the question round,
so the calls below marked *(builder's call)* are mine, not his.

## Why

The soundboard clips (tablet tiles, ~90 MP3s) are the moments the room remembers.
When the end-of-day summary and the wiki say "this is where we heard 7 Rings", and
link to the clip, the participant gets the concept back through the emotion. For
that, every clip needs a public (or at least shareable) URL, and the daemon needs
to know *when* each clip was fired.

## Decisions Victor made

- Every tablet clip is published to YouTube on his channel, **automatically, as a
  rule**: a new or changed clip gets published without anyone asking.
- Subtitles are set explicitly on the YouTube video, made from the same local
  captions the Mac shows (`SoundCaptions.swift`).
- **As many public as possible.** YouTube's own copyright check decides per clip:
  no claim → **public**; any claim/block → **unlisted** (the link still works).
- Upload goes through **YouTube Studio in a signed-in Chrome profile** (browser
  automation), not the Data API — unverified API projects get every upload locked
  private until a weeks-long audit.
- Tile activations are tracked, and the summary + wiki link the clip's YouTube URL
  as an emotional anchor at the topic where it was fired. "YouTube" / soundboard
  appears in the wiki's Sources list.

## Pieces and contracts

### 1. Press log — victor-effects (public repo)

Every press that `UsageCounts` counts (tablet `/sound/pressed/<file>`, `/alarm/start`,
thumbnail-panel presses, participant FX presses that reach the router) also appends
one line to a JSONL file, config key `pressLogFile`, default
`~/.victor-effects/presses.jsonl`:

```json
{"ts":"2026-10-22T17:32:01.123+03:00","file":"53b_7_rings.mp3","n":53,"layer":"b","source":"tablet"}
```

`ts` ISO-8601 with local offset; `n`/`layer` from `tiles.json` (`layer` = `"a"`|`"b"`,
`n` null if the file is not on the grid); `source` = `tablet` | `panel` | `other`.
Append-only, best-effort (a write failure logs and never blocks the press).

### 2. Captions export — victor-effects

`GET /sounds/captions` → for every asset in `tiles.json` (A and B):

```json
{"53b_7_rings.mp3": {"durationSeconds": 12.4,
                     "cues": [{"start": 0.0, "end": 6.0, "text": "♪ I want it, I got it ♪"}]}}
```

Built from `SoundCaptions.schedule(for:clipSeconds:)` with the real clip length, so
it is exactly what the Mac would show. Silent assets → `"cues": []`.

### 3. Publisher — victor-vibe-board (private repo), `tools/youtube-publish/`

- Ledger at the repo root, `youtube-publish.json` (NOT in `assets/`, which is mirrored
  into the app bundles):
  ```json
  {"53b_7_rings.mp3": {"sha256": "…", "videoId": "abc123", "url": "https://youtu.be/abc123",
                       "visibility": "unlisted", "copyright": "claimed",
                       "title": "…", "publishedAt": "2026-10-22T18:00:00+03:00"}}
  ```
  `copyright` = `none` | `claimed` | `blocked` | `unknown`.
- Render: tile image centred on a 1280×720 frame (blurred-tile background) + the MP3,
  H.264/AAC MP4 *(builder's call on look)*. `.srt` from `/sounds/captions`.
- Upload in YouTube Studio: title, description, "not made for kids", subtitles file
  (English, with timing), wait for the **Checks → Copyright** result, then Public
  (no issues) or Unlisted (anything else). Record the outcome in the ledger.
- Idempotent: only files whose sha256 differs from the ledger (or are missing) are
  published. A changed clip gets a new video; the old one is set to unlisted and its
  id kept in the entry's `previous` list *(builder's call)*.
- **The rule, automatic:** a git `post-commit` hook in victor-vibe-board runs the
  publisher in the background when `app/src/main/assets/*.mp3` or `tiles.json`
  changed; plus a test/check that lists tiles without a ledger entry, and a line in
  the repo's CLAUDE.md. Captions-first rule: a tile without a caption is not
  published (the existing `SoundCaptionsTests` guard).

### 4. Daemon + summarizer — training-assistant + victor-skills-private

- `daemon/soundboard/` reads the press log for a time window and joins it with the
  ledger and `tiles.json` → `[{ts, n, layer, file, title, caption, url}]`. CLI like
  the transcript one: `python3 -m daemon.soundboard.query <from_iso> <to_iso>`.
  Paths configurable, defaults as above.
- training-summarizer (private skill) gets the presses as a source (same way
  `zoom_chat.py` feeds the Zoom chat): each press is placed at its time in the
  transcript, and the summary/wiki note that owns that moment gets a link
  `[🎵 7 Rings](https://youtu.be/…)` as an emotional anchor. Clips with no URL yet are
  mentioned without a link.
- Wiki Sources panel lists the soundboard (`patch-graph.py` sources list).

## Non-goals (v1)

- The tablet's 🎬 Video Snippets page (already cut from YouTube videos) — not
  published, not logged. Follow-up if wanted.
- Deleting videos from YouTube.

## Related tablet changes requested the same day (separate, small)

#53b 7 Rings replaces #80 (the minion crowd goes); #61 Hallelujah trimmed with a
fade before the climax; #46b My Way starts ~1 s earlier; FX badge instead of ⭐;
countdown while a clip plays; larger, directly tappable layer-B corner; rule that a
new tile always gets a caption.
