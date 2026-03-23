import AppKit

/// Floating bar of round emoji buttons — always on top, draggable, click-through safe.
class ButtonBar: NSPanel {

    struct ButtonDef {
        let label: String      // emoji or text shown on button
        let tooltip: String
        let action: () -> Void
    }

    private let buttonSize: CGFloat = 40
    private let padding: CGFloat = 6
    private var trackingArea: NSTrackingArea?
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

        // Position: bottom area, ~20% from right edge
        let x = screen.frame.width * 0.80 - barWidth / 2
        let y: CGFloat = 80

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
        isMovableByWindowBackground = true
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]

        let container = NSView(frame: NSRect(x: 0, y: 0, width: barWidth, height: barHeight))
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
            options: [.mouseEnteredAndExited, .activeAlways],
            owner: self,
            userInfo: nil
        )
        container.addTrackingArea(ta)
    }

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

// MARK: - Round emoji button

private class RoundEmojiButton: NSView {
    private let label: String
    private let action: () -> Void
    private var isPressed = false
    private var textLayer: CATextLayer!
    private var bgLayer: CALayer!

    init(frame: NSRect, label: String, tooltip: String, action: @escaping () -> Void) {
        self.label = label
        self.action = action
        super.init(frame: frame)
        self.toolTip = tooltip
        wantsLayer = true

        bgLayer = CALayer()
        bgLayer.frame = bounds
        bgLayer.cornerRadius = bounds.width / 2
        bgLayer.backgroundColor = NSColor(white: 0.3, alpha: 0.8).cgColor
        layer?.addSublayer(bgLayer)

        textLayer = CATextLayer()
        textLayer.string = label
        textLayer.fontSize = 22
        textLayer.alignmentMode = .center
        textLayer.frame = CGRect(x: 0, y: (bounds.height - 28) / 2, width: bounds.width, height: 28)
        textLayer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        layer?.addSublayer(textLayer)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func mouseDown(with event: NSEvent) {
        isPressed = true
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = NSColor(white: 0.5, alpha: 0.9).cgColor
        layer?.setAffineTransform(CGAffineTransform(scaleX: 0.9, y: 0.9))
        CATransaction.commit()
    }

    override func mouseUp(with event: NSEvent) {
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = NSColor(white: 0.3, alpha: 0.8).cgColor
        layer?.setAffineTransform(.identity)
        CATransaction.commit()

        if isPressed {
            isPressed = false
            let loc = convert(event.locationInWindow, from: nil)
            if bounds.contains(loc) {
                action()
            }
        }
    }
}
