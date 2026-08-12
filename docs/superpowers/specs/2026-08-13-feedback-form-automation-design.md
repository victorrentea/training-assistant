# Feedback form automation — design

**Date:** 2026-08-13
**Status:** approved design, not yet planned

## Problem

At the end of every training session Victor manually creates a participant
feedback form on [freeonlinesurveys.com](https://freeonlinesurveys.com) (FOS) by
cloning the previous session's form and editing its title. The link then has to
reach participants by hand.

FOS has no public API for *creating* surveys (its "Javascript API" and
"Webhooks" serve response collection only) and it authenticates through Google
SSO, so the clone can only be driven through an authenticated browser session.

## Goal

When Victor runs the training-summarizer on the **last day** of a session, a
correctly titled feedback form exists and its link reaches him, the summary,
and every connected participant — without him touching the browser, and
without ever delaying `ai-summary.md`.

## Non-goals

- Migrating off FOS (its cross-session response history is the reason to stay).
- Automating the Google SSO login itself. If Chrome is not already
  authenticated, the automation stops and says so.
- Collecting or storing feedback responses. Those stay in FOS.

## Architecture

Three independent units, communicating through two well-defined values: the
derived **form title** (in) and the published **form URL** (out).

```
training-summarizer (last day only)
        │  title = "AI@Acme"
        ▼
  feedback-form skill  ──(Claude in Chrome)──▶  freeonlinesurveys.com
        │  {title, url, qr_png_path}
        ├──────────────▶ chat (main thread reports to Victor)
        ├──────────────▶ ai-summary.md  (## 📝 Feedback block)
        └──────────────▶ daemon POST /api/feedback-form
                                │
                                ├─ persist to <session folder>/feedback-form.json
                                ├─ session_shared_state.set_feedback_url(...)
                                └─ broadcast {feedback_url} ──▶ participant.html
                                                                 ├─ CTA card + QR
                                                                 └─ left-nav "Feedback form"
```

### Unit 1 — `feedback-form` skill (repo: `victorrentea/ai`)

Location: `~/workspace/ai/skills/feedback-form/SKILL.md`. Auto-discovered as
`victor-skills:feedback-form`; must be committed and pushed for Copilot CLI to
see it.

**Interface.** Input: `title` (string), `session_folder` (path). Output: JSON
`{title, url, qr_png_path}` on success, or a structured failure (see below).

**Dependencies.** Claude in Chrome, running against Victor's real Chrome
profile — that profile already holds the Google SSO session, which is why no
SSO automation is needed.

**Flow.**

1. Open the FOS dashboard in a **new tab** (never reuse an existing tab).
2. **Auth gate:** if the page is a login screen, stop immediately and return
   the "not authenticated" failure. Do not attempt Google SSO.
3. Locate the most recently modified survey and invoke its Duplicate/Clone
   action.
4. Open the clone, go to **Build**, set the title to the input `title`.
5. **Publish.** An unpublished clone serves no link ("Must be published…"
   notice on the Send screen), so this step is mandatory, not optional.
6. Go to **Send → Get a link (URL)** and read the
   `https://freeonlinesurveys.com/s/XXXXXXX` URL.
7. Click **DOWNLOAD PNG** on the same screen; save the QR into
   `<session folder>/feedback-qr.png`.

**Robustness.** Every step verifies by reading the page rather than clicking
blind. No step may trigger a native `alert`/`confirm` dialog (it would freeze
the extension). On the first successful run the skill records the concrete
selectors and navigation steps that worked, so subsequent runs are
deterministic rather than exploratory.

**Failure is never fatal.** Any failure — not logged in, UI changed, element
not found, publish rejected — returns a failure object carrying the dashboard
URL and the derived title, and the caller reports "create it by hand" to
Victor. Nothing downstream blocks on it.

**Dry-run mode.** A flag stops the flow after step 4 (retitled but unpublished)
so the automation can be exercised without creating a live client-facing form.

### Unit 2 — training-summarizer integration (repo: `victorrentea/ai`)

**Last-day detection.** Session folders are named
`YYYY-MM-DD[..DD] Topic@client`. Parse the date range; run only when today is
the last date. A single-date folder is trivially the last day.

**Title derivation.** The folder name minus its date prefix. `2026-08-11..13
AI@Acme` → `AI@Acme` — exactly the title format already in use on FOS. The
derived title is printed before it is used, so it lands in Victor's scrollback
even though the run is unattended.

**Scheduling.** Runs as a **background sub-agent**, launched with the rest of
the fan-out in Step 5, after `ai-summary.md` is on disk and the relay is up. It
can never delay the deliverable. It reports `{title, url}` back to the main
thread on completion.

**Autonomy.** Fully autonomous through publish, per explicit decision. The
residual risk — a misderived title going live to a client — is bounded: FOS
titles remain editable after publishing, so a bad title is recoverable, and the
printed title makes it visible.

### Unit 3 — daemon + participant page (repo: `training-assistant`)

Mirrors the existing `gdrive_url` mechanism end to end, because it is the same
shape of value: one session-scoped external URL, revealed in the left nav.

**Endpoint.** `POST /api/feedback-form`, strict Pydantic request model
(`FeedbackFormRequest{url: HttpUrl, title: str}`) and response model. Host-only,
behind the existing auth.

**Persistence — the one place this must NOT copy gdrive.** `daemon/session/state.py`
holds `_gdrive_url` as in-memory module state; it survives daemon restarts only
because `daemon/__main__.py` re-resolves it from the session folder at boot. The
daemon auto-restarts on every push to master, so an in-memory-only
`feedback_url` would silently vanish mid-session. Therefore:

- the endpoint writes `<session folder>/feedback-form.json`
  (`{title, url, created_at}`) as the source of truth, then sets shared state;
- daemon boot reads that file back into `session_shared_state.set_feedback_url(...)`,
  alongside the existing gdrive resolution;
- clearing the session clears it, exactly as `set_gdrive_url(None)` is cleared.

**State + broadcast.** `feedback_url` joins the participant state payload
(`daemon/participant/router.py`, next to `gdrive_url`) so reconnects and fresh
loads see it. The live update rides the **generic `broadcast` envelope**, so
**no `railway/**` change and no Railway deploy are needed** — it ships via the
daemon's static sync on push, like any other participant change.

**Participant UI.** Two layers, both driven off the single `feedback_url`:

1. **Left-nav item — "Feedback form"** (icon `rate_review`, with the
   `open_in_new` glyph). A hidden `#feedback-row` cloned in structure from
   `#gdrive-row` (`static/participant.html:795`): an
   `<a target="_blank" rel="noopener">` that opens FOS in a new tab, switches no
   view, and makes no daemon call. Revealed in **both** places gdrive is
   handled — the `state` applier (~`:3937`) and the broadcast handler (~`:4030`).
   This is the permanent way back to the form for the rest of the session.
2. **CTA card**, shown when the link first arrives — the attention grab for a
   room that is about to disperse. It is **dismissible, and dismissal is
   remembered per participant** (localStorage, as with other participant-local
   UI state), so a reconnect does not re-nag someone who has already filled it
   in. The nav item remains as the way back.

**No QR on the participant page.** A QR rendered on a participant's own phone
is useless — they are already on the device and can tap the link. The QR is for
the projector, so the skill saves it as `<session folder>/feedback-qr.png` and
Victor shows the file. `static/host.html` already loads `qrcodejs`, so
rendering it in the host UI instead is a cheap follow-up if wanted; the
participant page has no QR library and adding a CDN script there would fight
its CSP for no benefit.

**Naming.** The nav item is "Feedback form". There is **no competing UI element
to collide with**: `#feedback-view` (`static/participant.html:954`) and its
`sendFeedback()` handler have no nav entry and no caller — the view is
unreachable except by typing `/{session}/feedback`, and Victor has approved
deleting it. A parallel change is adding a "Report a bug" nav entry, which does
not collide either.

**Anonymity.** Participants click out to FOS, so no UUID or display name
follows them. Anonymity holds by construction, with nothing to enforce.

## Error handling

| Failure | Behaviour |
|---|---|
| Chrome not authenticated to FOS | Skill stops at the auth gate, reports the dashboard URL + derived title. No form created. |
| FOS UI changed / element missing | Same structured failure; nothing is left half-published if it fails before step 5. |
| Publish fails | Report failure including the draft's URL so Victor can publish manually. |
| Daemon unreachable | URL still reaches chat and `ai-summary.md`; only the participant-page delivery is lost. |
| Not the last day | Step is skipped silently. Not an error. |

The three delivery destinations are independent: one failing does not prevent
the others.

## Testing

- **Hermetic (Docker, per TESTING.md):** `POST /api/feedback-form` contract;
  `feedback_url` present in the participant state payload; broadcast reaches a
  connected participant; nav item appears; **link survives a daemon restart**
  (the regression this design exists to prevent).
- **OpenAPI snapshot** regenerated for the new endpoint; `API.md` regenerated
  via `python3 scripts/generate_apis_md.py --output API.md` — never edited
  directly.
- **Browser half:** not hermetically testable. Covered by the dry-run mode,
  exercised manually against FOS.
- **Visual proof:** screenshot of the participant left nav with the "Feedback
  form" item and of the CTA card.

## Open questions

None blocking. The FOS clone flow's exact selectors are unknown until the first
live run; the skill is written to discover and then record them, which is why
step 3–7 are specified by intent rather than by selector.
