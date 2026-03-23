import AppKit

/// Floating bar of round emoji buttons — always on top, draggable, clickable.
class ButtonBar: NSPanel {

    struct ButtonDef {
        let label: String      // emoji or text shown on button
        let tooltip: String
        let action: () -> Void
    }

    private let buttonSize: CGFloat = 40
    private let padding: CGFloat = 6
    private var fadeTimer: Timer?
    private let idleOpacity: CGFloat = 0.35
    private let hoverOpacity: CGFloat = 1.0

    init(buttons: [ButtonDef]) {
        guard let screen = NSScreen.screens.first else {
            fatalError("No screen available")
        }

        let count = CGFloat(buttons.count)
        let barWidth = count * buttonSize + (count + 1) * padding
        let barHeight = buttonSize + padding * 2

        // Position: flush with bottom edge, centered horizontally
        let x = (screen.frame.width - barWidth) / 2
        let y: CGFloat = 0

        let frame = NSRect(x: x, y: y, width: barWidth, height: barHeight)

        super.init(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        level = .statusBar + 1  // above the overlay panel
        // NOT using isMovableByWindowBackground — it steals button clicks
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        acceptsMouseMovedEvents = true
        becomesKeyOnlyIfNeeded = true

        let container = ButtonBarContainer(frame: NSRect(x: 0, y: 0, width: barWidth, height: barHeight))
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor(white: 0.15, alpha: 0.85).cgColor
        container.layer?.cornerRadius = barHeight / 2

        for (i, def) in buttons.enumerated() {
            let x = padding + CGFloat(i) * (buttonSize + padding)
            let btn = RoundEmojiButton(
                frame: NSRect(x: x, y: padding, width: buttonSize, height: buttonSize),
                label: def.label,
                tooltip: def.tooltip,
                action: def.action
            )
            container.addSubview(btn)
        }

        contentView = container

        // Start semi-transparent, fade in on hover
        alphaValue = idleOpacity

        // Tracking area for hover on the container view
        let ta = NSTrackingArea(
            rect: container.bounds,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        container.addTrackingArea(ta)
    }

    // Accept first click without requiring activation
    override var canBecomeKey: Bool { true }

    override func mouseEntered(with event: NSEvent) {
        fadeTimer?.invalidate()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.15
            self.animator().alphaValue = hoverOpacity
        }
    }

    override func mouseExited(with event: NSEvent) {
        fadeTimer?.invalidate()
        fadeTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.4
                self.animator().alphaValue = self.idleOpacity
            }
        }
    }
}

// MARK: - Container view (accepts first mouse, draggable by background)

private class ButtonBarContainer: NSView {
    private var dragOrigin: NSPoint?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { false }

    override func mouseDown(with event: NSEvent) {
        let loc = convert(event.locationInWindow, from: nil)
        // Only start drag if clicking on background (not on a button)
        let hitView = hitTest(convert(loc, to: superview))
        if hitView === self {
            dragOrigin = event.locationInWindow
        } else {
            super.mouseDown(with: event)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        guard let origin = dragOrigin, let window = self.window else {
            super.mouseDragged(with: event)
            return
        }
        let current = event.locationInWindow
        let dx = current.x - origin.x
        let dy = current.y - origin.y
        var frame = window.frame
        frame.origin.x += dx
        frame.origin.y += dy
        window.setFrame(frame, display: true)
        // Don't update dragOrigin — locationInWindow is relative to the window
    }

    override func mouseUp(with event: NSEvent) {
        dragOrigin = nil
        super.mouseUp(with: event)
    }
}

// MARK: - Round emoji button (click fires action, drag moves window)

private class RoundEmojiButton: NSView {
    private let action: () -> Void
    private var isPressed = false
    private var isDragging = false
    private var dragOrigin: NSPoint = .zero
    private var bgLayer: CALayer!
    private let dragThreshold: CGFloat = 3

    init(frame: NSRect, label: String, tooltip: String, action: @escaping () -> Void) {
        self.action = action
        super.init(frame: frame)
        self.toolTip = tooltip
        wantsLayer = true

        bgLayer = CALayer()
        bgLayer.frame = bounds
        bgLayer.cornerRadius = bounds.width / 2
        bgLayer.backgroundColor = NSColor(white: 0.3, alpha: 0.8).cgColor
        layer?.addSublayer(bgLayer)

        let textLayer = CATextLayer()
        textLayer.string = label
        textLayer.fontSize = 22
        textLayer.alignmentMode = .center
        textLayer.frame = CGRect(x: 0, y: (bounds.height - 28) / 2, width: bounds.width, height: 28)
        textLayer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        layer?.addSublayer(textLayer)
    }

    required init?(coder: NSCoder) { fatalError() }

    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseDown(with event: NSEvent) {
        isPressed = true
        isDragging = false
        dragOrigin = event.locationInWindow
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = NSColor(white: 0.5, alpha: 0.9).cgColor
        layer?.setAffineTransform(CGAffineTransform(scaleX: 0.9, y: 0.9))
        CATransaction.commit()
    }

    override func mouseDragged(with event: NSEvent) {
        let current = event.locationInWindow
        let dx = current.x - dragOrigin.x
        let dy = current.y - dragOrigin.y

        if !isDragging {
            // Check if we've moved past the drag threshold
            if abs(dx) > dragThreshold || abs(dy) > dragThreshold {
                isDragging = true
                isPressed = false
                // Reset button visual
                CATransaction.begin()
                CATransaction.setAnimationDuration(0.08)
                bgLayer.backgroundColor = NSColor(white: 0.3, alpha: 0.8).cgColor
                layer?.setAffineTransform(.identity)
                CATransaction.commit()
            }
        }

        if isDragging, let window = self.window {
            var frame = window.frame
            frame.origin.x += dx
            frame.origin.y += dy
            window.setFrame(frame, display: true)
        }
    }

    override func mouseUp(with event: NSEvent) {
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = NSColor(white: 0.3, alpha: 0.8).cgColor
        layer?.setAffineTransform(.identity)
        CATransaction.commit()

        if isPressed && !isDragging {
            let loc = convert(event.locationInWindow, from: nil)
            if bounds.contains(loc) {
                NSLog("Button tapped: \(toolTip ?? "?")")
                action()
            }
        }
        isPressed = false
        isDragging = false
    }
}
