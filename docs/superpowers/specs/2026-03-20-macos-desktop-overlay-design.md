# macOS Desktop Overlay — MVP Design Spec

## Goal

A native macOS app that renders floating reaction emojis on top of whatever is currently on the presenter's screen during live workshops, without disrupting normal desktop use.

## MVP Scope

- Auto-demo mode: spawn a ❤️ emoji every 1 second near the bottom-right corner
- Each emoji floats upward ~300pt while fading out, over ~2 seconds total, then is removed
- Desktop remains fully clickable — the overlay does not intercept any mouse events
- Works over normal windows and fullscreen apps

## Architecture

Single transparent, full-screen, click-through `NSPanel` with `CATextLayer` sublayers animated via `CABasicAnimation`.

### Why single overlay window (not many small windows)

- `NSWindow.ignoresMouseEvents = true` makes the entire window 100% click-through — no need for per-emoji windows to limit hit areas
- WindowServer composites each `NSWindow` separately; many small windows cause overhead
- Individual `CALayer` sublayers within one window are GPU-accelerated and efficient
- Cleanup (removing a sublayer) is trivial vs closing/deallocating windows

### Why no special permissions are needed

- The overlay draws only its own content — no Screen Recording permission
- No global hotkeys in MVP — no Accessibility permission
- No entitlements beyond standard app sandbox

## Components

### `OverlayPanel` (NSPanel subclass)

Configuration:
- `styleMask: [.borderless, .nonactivatingPanel]`
- `isOpaque = false`, `backgroundColor = .clear`, `hasShadow = false`
- `level = .statusBar` (25) — floats above most apps
- `ignoresMouseEvents = true` — all clicks pass through
- `collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]` — visible over fullscreen apps and across Spaces

### `EmojiAnimator`

Spawns emojis as `CATextLayer` instances on the overlay's content view layer:
- Font size: ~40pt
- Spawn position: bottom-right area, random horizontal offset ±50pt from a fixed X
- Animation group (CAAnimationGroup, duration ~2s):
  - `position.y`: move upward ~300pt (decreasing Y in layer coordinates)
  - `opacity`: fade from 1.0 to 0.0
- On completion: remove the layer from its superlayer via `CATransaction.setCompletionBlock` (note: `isRemovedOnCompletion` only removes the animation object, not the layer itself)

### `AppDelegate`

- Creates the `OverlayPanel` covering the primary display (`NSScreen.screens.first`; multi-display is future scope)
- Starts a 1-second `Timer` that calls `EmojiAnimator` to spawn a ❤️
- App runs as a standard macOS app (no LSUIElement yet — visible in Dock)

## Project Structure

```
desktop-overlay/
├── Package.swift
└── Sources/
    └── DesktopOverlay/
        ├── main.swift
        ├── AppDelegate.swift
        ├── OverlayPanel.swift
        └── EmojiAnimator.swift
```

## Bootstrap (`main.swift`)

With SPM (no Xcode project, no `Info.plist`), the app must be bootstrapped manually:

```swift
import AppKit
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
```

This replaces the `@main` / `@NSApplicationMain` pattern that requires an Xcode project.

## Package.swift

Minimum macOS deployment target: `.macOS(.v13)`. Single executable target `DesktopOverlay`, no external dependencies. The package depends only on system frameworks (AppKit, QuartzCore) which are available implicitly.

## Build & Run

```bash
cd desktop-overlay && swift run
```

Quit with Cmd+Q (app is visible in Dock).

## Technology Choices

| Concern | Choice | Rationale |
|---|---|---|
| Build system | Swift Package Manager | No Xcode GUI needed, terminal-only workflow |
| Window type | NSPanel | Non-activating, no focus steal |
| Animation | CATextLayer + CABasicAnimation | GPU-accelerated, efficient add/remove |
| App framework | AppKit | Required for NSWindow-level config; SwiftUI cannot configure these properties |

## Future Phases (out of MVP scope)

- HTTP endpoint or WebSocket client to receive reactions from workshop server
- Multiple emoji types
- Burst/cluster spawning
- Menu bar icon for control
- Rate limiting
- `LSUIElement = true` to hide from Dock
- `sharingType = .none` to hide from screen recordings if desired
