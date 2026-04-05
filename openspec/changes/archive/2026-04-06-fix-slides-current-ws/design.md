## Context

The daemon receives slide-change events from the macOS addon bridge (`{"type": "slide", "deck": "...", "slide": N}`), builds a slide metadata dict `_sc`, and is supposed to broadcast it to participants via `SlidesCurrentMsg`. The Pydantic model has a single `slides_current: Optional[dict]` field that wraps the entire metadata dict. The bug: the daemon calls `SlidesCurrentMsg(**_sc)`, which unpacks the dict as top-level keyword arguments — none of which match any field on the model — so `slides_current` stays `None`.

## Goals / Non-Goals

**Goals:**
- Participants receive a non-null `slides_current` dict when the host changes slide, enabling the follow feature to scroll correctly.

**Non-Goals:**
- No changes to the Pydantic model, Railway relay logic, participant JS, or WS protocol.

## Decisions

**Fix: wrap the dict, don't unpack it.**
Change `SlidesCurrentMsg(**_sc)` → `SlidesCurrentMsg(slides_current=_sc)` at every non-null broadcast call site in `daemon/__main__.py`.

Alternatives considered:
- Flatten `SlidesCurrentMsg` to accept individual fields (`url`, `slug`, `current_page`, …) — rejected because it would require changing the Railway relay and participant JS; the wrapper-dict approach is already in the contract.
- Add field aliases to the Pydantic model — rejected; adds complexity for no benefit.

## Risks / Trade-offs

- [Risk]: Missing a call site leaves the bug partially unfixed. → Mitigation: grep for all `SlidesCurrentMsg(` usages before patching.
