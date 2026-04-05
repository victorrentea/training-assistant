## Why

When participants have "follow" enabled, the WebSocket `slides_current` message arrives with `null` payload, so their browser never scrolls to the host's current slide. The addon-bridge correctly parses the slide from macOS addons, but the daemon builds the wrong Pydantic message — unpacking the slide dict as top-level keyword args instead of nesting it inside the `slides_current` field.

## What Changes

- Fix the daemon to construct `SlidesCurrentMsg(slides_current=_sc)` instead of `SlidesCurrentMsg(**_sc)` at the 2-4 call sites in `daemon/__main__.py` where a non-null slide is broadcast.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
<!-- none — this is a pure bug fix; no requirement changes -->

## Impact

- **`daemon/__main__.py`**: 2–4 lines changed (slide broadcast call sites).
- No API contract changes; `SlidesCurrentMsg` schema is already correct.
- No frontend changes needed; participant JS already handles the `slides_current` dict correctly when it is non-null.
