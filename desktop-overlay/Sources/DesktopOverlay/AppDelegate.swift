import AppKit
import Foundation

struct ScreenTopology {
    private static let mirrorTolerance: CGFloat = 1.0

    static func primaryIndex(frames: [CGRect]) -> Int {
        guard !frames.isEmpty else { return 0 }
        return frames.enumerated().min { lhs, rhs in
            if lhs.element.minY == rhs.element.minY {
                return lhs.element.minX < rhs.element.minX
            }
            return lhs.element.minY < rhs.element.minY
        }?.offset ?? 0
    }

    static func hasSecondaryDesktop(frames: [CGRect]) -> Bool {
        guard frames.count > 1 else { return false }
        let primary = frames[primaryIndex(frames: frames)]
        return frames.contains { frame in
            !isMirrorOfPrimary(frame, primary: primary)
        }
    }

    static func preferredButtonScreenIndex(frames: [CGRect]) -> Int {
        guard !frames.isEmpty else { return 0 }

        let primaryIdx = primaryIndex(frames: frames)
        let primary = frames[primaryIdx]
        let secondaryDesktops = frames.enumerated().filter { entry in
            entry.offset != primaryIdx && !isMirrorOfPrimary(entry.element, primary: primary)
        }
        guard !secondaryDesktops.isEmpty else { return primaryIdx }

        if let above = secondaryDesktops.first(where: { $0.element.minY >= primary.maxY - 50 }) {
            return above.offset
        }
        return secondaryDesktops[0].offset
    }

    private static func isMirrorOfPrimary(_ frame: CGRect, primary: CGRect) -> Bool {
        if abs(frame.minX - primary.minX) > mirrorTolerance { return false }
        if abs(frame.minY - primary.minY) > mirrorTolerance { return false }
        if abs(frame.width - primary.width) > mirrorTolerance { return false }
        if abs(frame.height - primary.height) > mirrorTolerance { return false }
        return true
    }
}

class AppDelegate: NSObject, NSApplicationDelegate, URLSessionWebSocketDelegate {
    private var overlayPanel: OverlayPanel!
    private var animator: EmojiAnimator!
    private var buttonBar: ButtonBar!
    private let serverURL: String
    private var wsTask: URLSessionWebSocketTask?
    private var session: URLSession!
    private var reconnecting = false
    private var pendingDisconnectError: DispatchWorkItem?
    private let disconnectErrorDelay: TimeInterval = 3.0
    private let pidFilePath: String
    private let myPID: Int32
    private var pidCheckTimer: Timer?

    init(serverURL: String, pidFilePath: String, myPID: Int32) {
        self.serverURL = serverURL
        self.pidFilePath = pidFilePath
        self.myPID = myPID
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let screens = NSScreen.screens
        guard !screens.isEmpty else { fatalError("No screens available") }
        let screenFrames = screens.map(\.frame)
        let primaryIdx = ScreenTopology.primaryIndex(frames: screenFrames)
        let buttonIdx = ScreenTopology.preferredButtonScreenIndex(frames: screenFrames)

        let singleScreen = !ScreenTopology.hasSecondaryDesktop(frames: screenFrames)
        let effectScreen = screens[primaryIdx] // built-in Mac display — effects always here
        let buttonScreen = screens[buttonIdx] // external desktop (or primary if single/mirror)

        overlayPanel = OverlayPanel(screen: effectScreen)
        overlayPanel.orderFrontRegardless()

        guard let hostLayer = overlayPanel.contentView?.layer else {
            fatalError("Content view has no layer")
        }
        animator = EmojiAnimator(hostLayer: hostLayer)

        session = URLSession(configuration: .default, delegate: self, delegateQueue: .main)
        connectWebSocket()
        setupButtonBar(screen: buttonScreen, singleScreen: singleScreen)


        // Check every 2s if another instance took over the PID file
        pidCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.checkPIDFile()
        }
    }

    // MARK: - Button bar

    private func setupButtonBar(screen: NSScreen, singleScreen: Bool) {
        let buttons: [ButtonBar.ButtonDef] = [
            .init(label: "❤️", tooltip: "Floating Heart") { [weak self] in
                self?.animator.spawnEmoji("❤️")
            },
            .init(label: "🎊", tooltip: "Confetti") { [weak self] in
                self?.animator.spawnConfetti()
            },
            .init(label: "🚨", tooltip: "Danger") { [weak self] in
                self?.animator.showDanger()
            },
            .init(label: "💥", tooltip: "Earthquake") { [weak self] in
                self?.animator.showEarthquake()
            },
            .init(label: "🎞️", tooltip: "Film burn") { [weak self] in
                self?.animator.showFilmBurn()
            },
            .init(label: "z", tooltip: "Zorro") { [weak self] in
                self?.animator.showZorro()
            },
            .init(label: "🎆", tooltip: "Fireworks") { [weak self] in
                self?.animator.showFireworks()
            },
            .init(label: "📽️", tooltip: "Sepia") { [weak self] in
                self?.animator.showSepia()
            },
            .init(label: "👏", tooltip: "Applause (toggle)") { [weak self] in
                self?.animator.showApplause()
            },
            .init(label: "💚", tooltip: "Pulse") { [weak self] in
                self?.animator.showPulse()
            },
        ]

        let fingerprint = ScreenFingerprint.current()
        // Position persistence only applies when ≥2 desktops are connected
        let savedOrigin = singleScreen ? nil : PositionStore.load(fingerprint: fingerprint)
        if let pos = savedOrigin {
            overlayInfo("Restoring button bar position \(Int(pos.x)),\(Int(pos.y)) for this monitor layout")
        }
        let onPositionChanged: ((NSPoint) -> Void)? = singleScreen ? nil : { origin in
            PositionStore.save(fingerprint: fingerprint, origin: origin)
        }

        buttonBar = ButtonBar(
            buttons: buttons,
            screen: screen,
            singleScreen: singleScreen,
            savedOrigin: savedOrigin,
            onPositionChanged: onPositionChanged
        )
        buttonBar.orderFrontRegardless()
    }

    private func checkPIDFile() {
        guard let content = try? String(contentsOfFile: pidFilePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
              let filePID = Int32(content) else {
            return
        }
        if filePID != myPID {
            overlayInfo("Replaced by newer instance — exiting")
            pidCheckTimer?.invalidate()
            wsTask?.cancel(with: .goingAway, reason: nil)
            NSApplication.shared.terminate(nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    // MARK: - WebSocket

    private func connectWebSocket() {
        reconnecting = false
        wsTask?.cancel(with: .goingAway, reason: nil)
        let wsURL = serverURL.replacingOccurrences(of: "http://", with: "ws://")
                             .replacingOccurrences(of: "https://", with: "wss://")
        guard let url = URL(string: "\(wsURL)/ws/__overlay__") else {
            overlayError("Invalid server URL: \(serverURL)")
            return
        }
        wsTask = session.webSocketTask(with: url)
        wsTask?.resume()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        cancelPendingDisconnectError()
        // Send set_name as required by protocol
        let msg = "{\"type\":\"set_name\",\"name\":\"Overlay\"}"
        wsTask?.send(.string(msg)) { error in
            if let error = error {
                overlayError("Handshake failed, retrying...")
            }
        }
        receiveMessage()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        scheduleDisconnectError()
        scheduleReconnect()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let _ = error {
            scheduleDisconnectError()
            scheduleReconnect()
        }
    }

    private func receiveMessage() {
        wsTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    self?.handleMessage(text)
                default:
                    break
                }
                self?.receiveMessage()
            case .failure:
                self?.scheduleDisconnectError()
                self?.scheduleReconnect()
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else {
            return
        }

        if type == "emoji_reaction", let emoji = json["emoji"] as? String {
            DispatchQueue.main.async { [weak self] in
                self?.animator.spawnEmoji(emoji)
            }
        } else if type == "confetti" {
            DispatchQueue.main.async { [weak self] in
                self?.animator.spawnConfetti()
            }
        }
    }

    private func scheduleReconnect() {
        guard !reconnecting else { return }
        reconnecting = true
        wsTask?.cancel(with: .goingAway, reason: nil)
        wsTask = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            self?.connectWebSocket()
        }
    }

    private func scheduleDisconnectError() {
        guard pendingDisconnectError == nil else { return }
        let work = DispatchWorkItem { [weak self] in
            self?.pendingDisconnectError = nil
            overlayError("WebSocket not connected")
        }
        pendingDisconnectError = work
        DispatchQueue.main.asyncAfter(deadline: .now() + disconnectErrorDelay, execute: work)
    }

    private func cancelPendingDisconnectError() {
        pendingDisconnectError?.cancel()
        pendingDisconnectError = nil
    }
}
