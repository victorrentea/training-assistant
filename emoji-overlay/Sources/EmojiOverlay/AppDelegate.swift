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

        // Auto-demo: spawn a random emoji every second
        demoTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.animator.spawnRandomEmoji()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}
