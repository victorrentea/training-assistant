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
