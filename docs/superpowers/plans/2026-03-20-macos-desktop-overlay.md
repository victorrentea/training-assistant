# macOS Desktop Overlay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP macOS app that renders floating ❤️ emojis on top of all other apps without blocking clicks.

**Architecture:** Single transparent, click-through NSPanel covering the primary screen. Emojis are CATextLayer sublayers animated with CABasicAnimation (float up + fade out). A 1-second timer spawns one emoji per tick in auto-demo mode.

**Tech Stack:** Swift, AppKit (NSPanel), Core Animation (CATextLayer, CABasicAnimation), Swift Package Manager

**Spec:** `docs/superpowers/specs/2026-03-20-macos-desktop-overlay-design.md`

---

## File Structure

```
desktop-overlay/
├── Package.swift                      ← SPM manifest, macOS 13+, single executable target
└── Sources/
    └── DesktopOverlay/
        ├── main.swift                 ← Manual NSApplication bootstrap
        ├── AppDelegate.swift          ← Creates overlay, starts demo timer
        ├── OverlayPanel.swift         ← NSPanel subclass with overlay config
        └── EmojiAnimator.swift        ← Spawns and animates emoji layers
```

---

### Task 1: Create SPM package scaffold

**Files:**
- Create: `desktop-overlay/Package.swift`
- Create: `desktop-overlay/Sources/DesktopOverlay/main.swift`

- [ ] **Step 1: Create Package.swift**

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DesktopOverlay",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "DesktopOverlay")
    ]
)
```

- [ ] **Step 2: Create minimal main.swift**

```swift
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.regular)
app.run()
```

- [ ] **Step 3: Build and verify it compiles**

Run: `cd desktop-overlay && swift build 2>&1`
Expected: "Build complete!"

- [ ] **Step 4: Commit**

```bash
git add desktop-overlay/Package.swift desktop-overlay/Sources/DesktopOverlay/main.swift
git commit -m "feat: scaffold SPM package for Desktop Overlay app"
```

---

### Task 2: Create OverlayPanel

**Files:**
- Create: `desktop-overlay/Sources/DesktopOverlay/OverlayPanel.swift`

- [ ] **Step 1: Write OverlayPanel class**

```swift
import AppKit

class OverlayPanel: NSPanel {
    init() {
        guard let screen = NSScreen.screens.first else {
            fatalError("No screen available")
        }
        super.init(
            contentRect: screen.frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        level = .statusBar
        ignoresMouseEvents = true
        collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
            .ignoresCycle
        ]
        let view = NSView(frame: screen.frame)
        view.wantsLayer = true
        contentView = view
    }
}
```

- [ ] **Step 2: Build and verify it compiles**

Run: `cd desktop-overlay && swift build 2>&1`
Expected: "Build complete!" (with a warning about unused OverlayPanel — that's fine)

- [ ] **Step 3: Commit**

```bash
git add desktop-overlay/Sources/DesktopOverlay/OverlayPanel.swift
git commit -m "feat: add OverlayPanel — transparent click-through NSPanel"
```

---

### Task 3: Create EmojiAnimator

**Files:**
- Create: `desktop-overlay/Sources/DesktopOverlay/EmojiAnimator.swift`

- [ ] **Step 1: Write EmojiAnimator class**

```swift
import AppKit
import QuartzCore

class EmojiAnimator {
    private let hostLayer: CALayer

    init(hostLayer: CALayer) {
        self.hostLayer = hostLayer
    }

    func spawnEmoji(_ emoji: String = "❤️") {
        let bounds = hostLayer.bounds

        // Spawn in bottom-right area with ±50pt random horizontal offset
        let baseX = bounds.maxX - 100
        let offsetX = CGFloat.random(in: -50...50)
        let spawnY: CGFloat = 80  // near bottom in layer coords (origin bottom-left)

        let layer = CATextLayer()
        layer.string = emoji
        layer.fontSize = 40
        layer.alignmentMode = .center
        layer.frame = CGRect(x: baseX + offsetX - 25, y: spawnY, width: 50, height: 50)
        layer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        hostLayer.addSublayer(layer)

        // Animate: float up 300pt + fade out, 2 seconds
        let moveUp = CABasicAnimation(keyPath: "position.y")
        moveUp.toValue = layer.position.y + 300

        let fadeOut = CABasicAnimation(keyPath: "opacity")
        fadeOut.toValue = 0.0

        let group = CAAnimationGroup()
        group.animations = [moveUp, fadeOut]
        group.duration = 2.0
        group.fillMode = .forwards
        group.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock { [weak layer] in
            layer?.removeFromSuperlayer()
        }
        layer.add(group, forKey: "floatAndFade")
        CATransaction.commit()
    }
}
```

Note on coordinate system: NSView with `wantsLayer = true` uses a flipped-from-screen coordinate system where Y=0 is at the bottom of the view. So `spawnY = 80` is near the bottom, and `position.y + 300` moves upward. If the layer appears at the top instead, flip the direction — the coordinate system depends on whether the view is flipped.

- [ ] **Step 2: Build and verify it compiles**

Run: `cd desktop-overlay && swift build 2>&1`
Expected: "Build complete!"

- [ ] **Step 3: Commit**

```bash
git add desktop-overlay/Sources/DesktopOverlay/EmojiAnimator.swift
git commit -m "feat: add EmojiAnimator — float-up-and-fade emoji layers"
```

---

### Task 4: Wire it all together in AppDelegate

**Files:**
- Create: `desktop-overlay/Sources/DesktopOverlay/AppDelegate.swift`
- Modify: `desktop-overlay/Sources/DesktopOverlay/main.swift`

- [ ] **Step 1: Write AppDelegate**

```swift
import AppKit

class AppDelegate: NSObject, NSApplicationDelegate {
    private var overlayPanel: OverlayPanel!
    private var animator: EmojiAnimator!
    private var demoTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        overlayPanel = OverlayPanel()
        overlayPanel.orderFrontRegardless()

        guard let hostLayer = overlayPanel.contentView?.layer else {
            fatalError("Content view has no layer")
        }
        animator = EmojiAnimator(hostLayer: hostLayer)

        // Auto-demo: spawn one ❤️ every second
        demoTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.animator.spawnEmoji()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}
```

- [ ] **Step 2: Update main.swift to use AppDelegate**

```swift
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
```

- [ ] **Step 3: Build**

Run: `cd desktop-overlay && swift build 2>&1`
Expected: "Build complete!"

- [ ] **Step 4: Commit**

```bash
git add desktop-overlay/Sources/DesktopOverlay/AppDelegate.swift desktop-overlay/Sources/DesktopOverlay/main.swift
git commit -m "feat: wire AppDelegate with demo timer — app is runnable"
```

---

### Task 5: Run and verify visually

- [ ] **Step 1: Run the app**

Run: `cd desktop-overlay && swift run`

Expected behavior:
- App appears in Dock
- ❤️ emojis spawn near the bottom-right of the screen every second
- Each emoji floats upward and fades out over 2 seconds
- Desktop underneath remains fully clickable (test by clicking on other windows/apps while emojis are visible)

- [ ] **Step 2: Fix coordinate direction if needed**

If emojis appear at the top and float further up (wrong direction), the view's coordinate system is flipped. In that case, change `EmojiAnimator.swift`:
- Set `spawnY` to `bounds.maxY - 80` instead of `80`
- Change `moveUp.toValue` to `layer.position.y - 300` instead of `+ 300`

- [ ] **Step 3: Commit any fixes**

```bash
git add -A desktop-overlay/Sources/
git commit -m "fix: adjust emoji spawn position and animation direction"
```

(Skip this commit if no fixes were needed.)
