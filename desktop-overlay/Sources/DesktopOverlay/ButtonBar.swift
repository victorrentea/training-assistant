import AppKit

struct SingleScreenHoverLogic {
    let shownFrame: NSRect

    func shouldSlideIn(mouse: NSPoint) -> Bool {
        return shownFrame.contains(mouse)
    }
}

/// Floating vertical bar of round emoji buttons — always on top, clickable.
/// Positioned at the right edge of the screen, slides in on hover.
/// Draggable vertically only.
class ButtonBar: NSPanel {
    static let autoHideDelay: TimeInterval = 1.0

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

    private let hoverOpacity: CGFloat = 1.0

    private var slideTimer: Timer?
    private var globalMouseMonitor: Any?
    private var localMouseMonitor: Any?
    private var hiddenFrame: NSRect = .zero
    private var shownFrame: NSRect = .zero
    private var isSlideIn: Bool = false

    init(buttons: [ButtonDef], screen: NSScreen) {
        let buttonSize: CGFloat = 32
        let padding: CGFloat = 5

        let count = CGFloat(buttons.count)
        let barWidth = buttonSize + padding * 2
        let barHeight = count * buttonSize + (count + 1) * padding

        let sf = screen.frame
        let preferredY = sf.minY + sf.height * 0.2
        let barY = max(sf.minY + 12, min(preferredY, sf.maxY - barHeight - 12))

        let initialFrame = NSRect(x: sf.maxX, y: barY, width: barWidth, height: barHeight)

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

        hiddenFrame = NSRect(x: sf.maxX, y: barY, width: barWidth, height: barHeight)
        shownFrame  = NSRect(x: sf.maxX - barWidth - 12, y: barY, width: barWidth, height: barHeight)

        let onDragEnded: (NSPoint) -> Void = { [weak self] origin in
            guard let self = self else { return }
            self.shownFrame.origin.y = origin.y
            self.hiddenFrame.origin.y = origin.y
        }

        let container = ButtonBarContainer(frame: NSRect(x: 0, y: 0, width: barWidth, height: barHeight),
                                           onDragEnded: onDragEnded)
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor(white: 0.15, alpha: 0.85).cgColor
        container.layer?.cornerRadius = min(barWidth, barHeight) / 2

        for (i, def) in buttons.enumerated() {
            let bx = padding
            let by = barHeight - padding - buttonSize - CGFloat(i) * (buttonSize + padding)
            let btn = RoundEmojiButton(
                frame: NSRect(x: bx, y: by, width: buttonSize, height: buttonSize),
                label: def.label,
                tooltip: def.tooltip,
                labelColor: def.labelColor,
                onDragEnded: onDragEnded,
                action: def.action
            )
            container.addSubview(btn)
        }

        contentView = container
        alphaValue = 0.0
        setupGlobalMouseMonitor()
    }

    override var canBecomeKey: Bool { true }

    // MARK: - Slide on global mouse position

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
        let logic = SingleScreenHoverLogic(shownFrame: shownFrame)
        if logic.shouldSlideIn(mouse: mouse) {
            slideIn()
            slideTimer?.invalidate()
            slideTimer = nil
            // Don't schedule slide-out while mouse is over the bar
        } else if isSlideIn && slideTimer == nil {
            scheduleSlideOut(after: ButtonBar.autoHideDelay)
        }
    }

    private func slideIn() {
        guard !isSlideIn else { return }
        isSlideIn = true
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.1
            self.animator().setFrame(shownFrame, display: true)
            self.animator().alphaValue = hoverOpacity
        }
    }

    private func scheduleSlideOut(after delay: TimeInterval) {
        guard slideTimer == nil else { return }
        slideTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
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
}

// MARK: - Drag helpers

private func clampedY(for frame: NSRect, on window: NSWindow) -> CGFloat {
    let margin: CGFloat = 12
    let sf = (window.screen ?? NSScreen.screens[0]).frame
    return max(sf.minY + margin, min(frame.origin.y, sf.maxY - frame.height - margin))
}

// MARK: - Container view (vertically draggable by background)

private class ButtonBarContainer: NSView {
    private var dragOrigin: NSPoint?
    private let onDragEnded: (NSPoint) -> Void

    init(frame: NSRect, onDragEnded: @escaping (NSPoint) -> Void) {
        self.onDragEnded = onDragEnded
        super.init(frame: frame)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { false }

    override func mouseDown(with event: NSEvent) {
        let loc = convert(event.locationInWindow, from: nil)
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
        let dy = event.locationInWindow.y - origin.y
        var frame = window.frame
        frame.origin.y = clampedY(for: NSRect(x: frame.origin.x, y: frame.origin.y + dy, width: frame.width, height: frame.height), on: window)
        window.setFrame(frame, display: true)
    }

    override func mouseUp(with event: NSEvent) {
        let hadDrag = dragOrigin != nil
        dragOrigin = nil
        super.mouseUp(with: event)
        if hadDrag, let origin = window?.frame.origin {
            onDragEnded(origin)
        }
    }
}

// MARK: - Round emoji button

private class RoundEmojiButton: NSView {
    private let action: () -> Void
    private let onDragEnded: (NSPoint) -> Void
    private var isPressed = false
    private var isDragging = false
    private var dragOrigin: NSPoint = .zero
    private var bgLayer: CALayer!
    private let dragThreshold: CGFloat = 3
    private let hoverBgColor = NSColor(white: 0.75, alpha: 0.45).cgColor
    private let pressBgColor = NSColor(white: 0.75, alpha: 0.75).cgColor

    init(frame: NSRect, label: String, tooltip: String, labelColor: CGColor? = nil,
         onDragEnded: @escaping (NSPoint) -> Void, action: @escaping () -> Void) {
        self.action = action
        self.onDragEnded = onDragEnded
        super.init(frame: frame)
        self.toolTip = tooltip
        wantsLayer = true

        bgLayer = CALayer()
        bgLayer.frame = bounds
        bgLayer.cornerRadius = bounds.width / 2
        bgLayer.backgroundColor = hoverBgColor
        bgLayer.opacity = 0
        layer?.addSublayer(bgLayer)

        let fontSize = bounds.width * 0.55
        let textHeight = bounds.width * 0.70
        let textLayer = CATextLayer()
        if let color = labelColor {
            let attr = NSAttributedString(string: label, attributes: [
                .foregroundColor: NSColor(cgColor: color) ?? .white,
                .font: NSFont.systemFont(ofSize: fontSize)
            ])
            textLayer.string = attr
        } else {
            textLayer.string = label
            textLayer.fontSize = fontSize
        }
        textLayer.alignmentMode = .center
        textLayer.frame = CGRect(x: 0, y: (bounds.height - textHeight) / 2, width: bounds.width, height: textHeight)
        textLayer.contentsScale = NSScreen.screens.first?.backingScaleFactor ?? 2.0
        layer?.addSublayer(textLayer)

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
        CATransaction.commit()
    }

    override func mouseExited(with event: NSEvent) {
        guard !isPressed else { return }
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.2)
        bgLayer.opacity = 0
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
            layer?.setAffineTransform(.identity)
            CATransaction.commit()
        }

        if isDragging, let window = self.window {
            var frame = window.frame
            frame.origin.y = clampedY(for: NSRect(x: frame.origin.x, y: frame.origin.y + dy, width: frame.width, height: frame.height), on: window)
            window.setFrame(frame, display: true)
        }
    }

    override func mouseUp(with event: NSEvent) {
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.08)
        bgLayer.backgroundColor = hoverBgColor
        bgLayer.opacity = 0
        layer?.setAffineTransform(.identity)
        CATransaction.commit()

        if isDragging, let origin = window?.frame.origin {
            onDragEnded(origin)
        }
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
