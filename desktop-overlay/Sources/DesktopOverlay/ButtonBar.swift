import AppKit

/// Floating bar of round emoji buttons — always on top, clickable.
/// Multi-screen: centered at bottom of target screen, fades on hover.
/// Single-screen: vertical stack at right edge (20% from bottom), slides in on hover.
class ButtonBar: NSPanel {

    struct ButtonDef {
        let label: String
        let tooltip: String
        let labelColor: CGColor?
        let action: () -> Void

        init(label: String, tooltip: String, labelColor: CGColor? = nil, action: @escaping () -> Void) {
            self.label = label
            self.tooltip = tooltip
            self.labelColor = labelColor
            self.action = action
        }
    }

    private let buttonSize: CGFloat = 40
    private let padding: CGFloat = 6
    private let idleOpacity: CGFloat = 0.35
    private let hoverOpacity: CGFloat = 1.0
    private let isSingleScreen: Bool

    // Multi-screen hover fade
    private var fadeTimer: Timer?

    // Single-screen slide
    private var slideTimer: Timer?
    private var globalMouseMonitor: Any?
    private var localMouseMonitor: Any?
    private var hiddenFrame: NSRect = .zero
    private var shownFrame: NSRect = .zero
    private var isSlideIn: Bool = false
    private let edgeTriggerDistance: CGFloat = 80

    init(buttons: [ButtonDef], screen: NSScreen, singleScreen: Bool) {
        self.isSingleScreen = singleScreen

        let count = CGFloat(buttons.count)
        let barWidth: CGFloat
        let barHeight: CGFloat
        if singleScreen {
            barWidth = buttonSize + padding * 2
            barHeight = count * buttonSize + (count + 1) * padding
        } else {
            barWidth = count * buttonSize + (count + 1) * padding
            barHeight = buttonSize + padding * 2
        }
        let sf = screen.frame

        let initialFrame: NSRect
        if singleScreen {
            // Start hidden: off the right edge, 20% from screen bottom
            let preferredY = sf.minY + sf.height * 0.2
            let barY = max(sf.minY + 12, min(preferredY, sf.maxY - barHeight - 12))
            initialFrame = NSRect(x: sf.maxX, y: barY, width: barWidth, height: barHeight)
        } else {
            // Centered at the bottom of the target screen
            let x = sf.midX - barWidth / 2
            initialFrame = NSRect(x: x, y: sf.minY, width: barWidth, height: barHeight)
        }

        super.init(
            contentRect: initialFrame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        level = .statusBar + 1
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        acceptsMouseMovedEvents = true
        becomesKeyOnlyIfNeeded = true

        let container = ButtonBarContainer(frame: NSRect(x: 0, y: 0, width: barWidth, height: barHeight),
                                           dragEnabled: !singleScreen)
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor(white: 0.15, alpha: 0.85).cgColor
        container.layer?.cornerRadius = min(barWidth, barHeight) / 2

        for (i, def) in buttons.enumerated() {
            let bx: CGFloat
            let by: CGFloat
            if singleScreen {
                bx = padding
                by = barHeight - padding - buttonSize - CGFloat(i) * (buttonSize + padding)
            } else {
                bx = padding + CGFloat(i) * (buttonSize + padding)
                by = padding
            }
            let btn = RoundEmojiButton(
                frame: NSRect(x: bx, y: by, width: buttonSize, height: buttonSize),
                label: def.label,
                tooltip: def.tooltip,
                labelColor: def.labelColor,
                action: def.action
            )
            container.addSubview(btn)
        }

        contentView = container

        if singleScreen {
            alphaValue = 0.0
            let preferredY = sf.minY + sf.height * 0.2
            let barY = max(sf.minY + 12, min(preferredY, sf.maxY - barHeight - 12))
            hiddenFrame = NSRect(x: sf.maxX, y: barY, width: barWidth, height: barHeight)
            shownFrame  = NSRect(x: sf.maxX - barWidth - 12, y: barY, width: barWidth, height: barHeight)
            setupGlobalMouseMonitor()
        } else {
            alphaValue = idleOpacity
            let ta = NSTrackingArea(
                rect: container.bounds,
                options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                owner: self,
                userInfo: nil
            )
            container.addTrackingArea(ta)
        }
    }

    override var canBecomeKey: Bool { true }

    // MARK: - Single-screen: slide on global mouse position

    private func setupGlobalMouseMonitor() {
        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: .mouseMoved) { [weak self] _ in
            self?.checkMouseForEdge()
        }
        localMouseMonitor = NSEvent.addLocalMonitorForEvents(matching: .mouseMoved) { [weak self] event in
            self?.checkMouseForEdge()
            return event
        }
    }

    private func checkMouseForEdge() {
        let mouse = NSEvent.mouseLocation
        let nearEdge = mouse.x >= hiddenFrame.minX - edgeTriggerDistance
        let onBar = shownFrame.insetBy(dx: -20, dy: -20).contains(mouse)

        if nearEdge || onBar {
            slideIn()
        } else if isSlideIn {
            scheduleSlideOut()
        }
    }

    private func slideIn() {
        slideTimer?.invalidate()
        slideTimer = nil
        guard !isSlideIn else { return }
        isSlideIn = true
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.1
            self.animator().setFrame(shownFrame, display: true)
            self.animator().alphaValue = hoverOpacity
        }
    }

    private func scheduleSlideOut() {
        guard slideTimer == nil else { return }
        slideTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: false) { [weak self] _ in
            self?.slideOut()
            self?.slideTimer = nil
        }
    }

    private func slideOut() {
        isSlideIn = false
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.25
            self.animator().setFrame(hiddenFrame, display: true)
            self.animator().alphaValue = 0.0
        }
    }

    deinit {
        if let m = globalMouseMonitor { NSEvent.removeMonitor(m) }
        if let m = localMouseMonitor  { NSEvent.removeMonitor(m) }
    }

    // MARK: - Multi-screen: hover fade

    override func mouseEntered(with event: NSEvent) {
        guard !isSingleScreen else { return }
        fadeTimer?.invalidate()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.15
            self.animator().alphaValue = hoverOpacity
        }
    }

    override func mouseExited(with event: NSEvent) {
        guard !isSingleScreen else { return }
        fadeTimer?.invalidate()
        fadeTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.4
                self.animator().alphaValue = self.idleOpacity
            }
        }
    }
}

// MARK: - Container view (draggable by background in multi-screen mode)

private class ButtonBarContainer: NSView {
    private var dragOrigin: NSPoint?
    private let dragEnabled: Bool

    init(frame: NSRect, dragEnabled: Bool) {
        self.dragEnabled = dragEnabled
        super.init(frame: frame)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { false }

    override func mouseDown(with event: NSEvent) {
        guard dragEnabled else { return }
        let loc = convert(event.locationInWindow, from: nil)
        let hitView = hitTest(convert(loc, to: superview))
        if hitView === self {
            dragOrigin = event.locationInWindow
        } else {
            super.mouseDown(with: event)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        guard dragEnabled, let origin = dragOrigin, let window = self.window else {
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
    }

    override func mouseUp(with event: NSEvent) {
        dragOrigin = nil
        super.mouseUp(with: event)
    }
}

// MARK: - Round emoji button

private class RoundEmojiButton: NSView {
    private let action: () -> Void
    private var isPressed = false
    private var isDragging = false
    private var dragOrigin: NSPoint = .zero
    private var bgLayer: CALayer!
    private var underlineLayer: CALayer!
    private let dragThreshold: CGFloat = 3
    private let hoverBgColor = NSColor(white: 0.75, alpha: 0.45).cgColor
    private let pressBgColor = NSColor(white: 0.75, alpha: 0.75).cgColor

    init(frame: NSRect, label: String, tooltip: String, labelColor: CGColor? = nil, action: @escaping () -> Void) {
        self.action = action
        super.init(frame: frame)
        self.toolTip = tooltip
        wantsLayer = true

        // Background: invisible by default, shows light gray on hover
        bgLayer = CALayer()
        bgLayer.frame = bounds
        bgLayer.cornerRadius = bounds.width / 2
        bgLayer.backgroundColor = hoverBgColor
        bgLayer.opacity = 0
        layer?.addSublayer(bgLayer)

        let textLayer = CATextLayer()
        if let color = labelColor {
            let attr = NSAttributedString(string: label, attributes: [
                .foregroundColor: NSColor(cgColor: color) ?? .white,
                .font: NSFont.systemFont(ofSize: 20)
            ])
            textLayer.string = attr
        } else {
            textLayer.string = label
            textLayer.fontSize = 22
        }
        textLayer.alignmentMode = .center
        textLayer.frame = CGRect(x: 0, y: (bounds.height - 28) / 2, width: bounds.width, height: 28)
        textLayer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        layer?.addSublayer(textLayer)

        // Underline: thin line at bottom, hidden by default
        underlineLayer = CALayer()
        let ulColor = labelColor ?? NSColor(white: 0.85, alpha: 0.9).cgColor
        underlineLayer.backgroundColor = ulColor
        underlineLayer.frame = CGRect(x: 5, y: 1, width: bounds.width - 10, height: 2)
        underlineLayer.cornerRadius = 1
        underlineLayer.opacity = 0
        layer?.addSublayer(underlineLayer)

        let ta = NSTrackingArea(rect: bounds,
                                options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                owner: self, userInfo: nil)
        addTrackingArea(ta)
    }

    required init?(coder: NSCoder) { fatalError() }

    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseEntered(with event: NSEvent) {
        guard !isPressed else { return }
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.12)
        bgLayer.opacity = 1
        underlineLayer.opacity = 1
        CATransaction.commit()
    }

    override func mouseExited(with event: NSEvent) {
        guard !isPressed else { return }
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.2)
        bgLayer.opacity = 0
        underlineLayer.opacity = 0
        CATransaction.commit()
    }

    override func mouseDown(with event: NSEvent) {
        isPressed = true
        isDragging = false
        dragOrigin = event.locationInWindow
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = pressBgColor
        bgLayer.opacity = 1
        underlineLayer.opacity = 1
        layer?.setAffineTransform(CGAffineTransform(scaleX: 0.9, y: 0.9))
        CATransaction.commit()
    }

    override func mouseDragged(with event: NSEvent) {
        let current = event.locationInWindow
        let dx = current.x - dragOrigin.x
        let dy = current.y - dragOrigin.y

        if !isDragging && (abs(dx) > dragThreshold || abs(dy) > dragThreshold) {
            isDragging = true
            isPressed = false
            CATransaction.begin()
            CATransaction.setAnimationDuration(0.08)
            bgLayer.backgroundColor = hoverBgColor
            bgLayer.opacity = 0
            underlineLayer.opacity = 0
            layer?.setAffineTransform(.identity)
            CATransaction.commit()
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
        bgLayer.backgroundColor = hoverBgColor
        bgLayer.opacity = 0
        underlineLayer.opacity = 0
        layer?.setAffineTransform(.identity)
        CATransaction.commit()

        if isPressed && !isDragging {
            let loc = convert(event.locationInWindow, from: nil)
            if bounds.contains(loc) {
                action()
            }
        }
        isPressed = false
        isDragging = false
    }
}
