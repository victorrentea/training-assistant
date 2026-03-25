import AppKit
import Foundation

class AppDelegate: NSObject, NSApplicationDelegate, URLSessionWebSocketDelegate {
    private var overlayPanel: OverlayPanel!
    private var animator: EmojiAnimator!
    private var buttonBar: ButtonBar!
    private let serverURL: String
    private var wsTask: URLSessionWebSocketTask?
    private var session: URLSession!
    private var reconnecting = false
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
        let singleScreen = NSScreen.screens.count == 1
        let effectScreen = primaryScreen()   // built-in Mac display — effects always here
        let buttonScreen = preferredScreen() // external monitor above Mac (or primary if single)

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

    // MARK: - Screen selection

    /// Returns the primary/built-in screen (lowest Y origin — the MacBook display).
    private func primaryScreen() -> NSScreen {
        return NSScreen.screens.min(by: { $0.frame.minY < $1.frame.minY }) ?? NSScreen.screens[0]
    }

    /// Returns the preferred screen for the button bar.
    /// With multiple screens, prefers an external screen positioned above the primary (built-in).
    /// Falls back to any non-primary screen, then the primary.
    private func preferredScreen() -> NSScreen {
        let screens = NSScreen.screens
        guard screens.count > 1 else { return screens[0] }

        // Primary screen: lowest Y origin (typically the built-in MacBook display)
        guard let primary = screens.min(by: { $0.frame.minY < $1.frame.minY }) else {
            return screens[0]
        }

        // Prefer a screen whose bottom edge aligns with the top of the primary (positioned above)
        let aboveScreens = screens.filter { $0 !== primary && $0.frame.minY >= primary.frame.maxY - 50 }
        if let above = aboveScreens.first { return above }

        // Fallback: any non-primary screen
        return screens.first(where: { $0 !== primary }) ?? screens[0]
    }

    // MARK: - Button bar

    private func setupButtonBar(screen: NSScreen, singleScreen: Bool) {
        let buttons: [ButtonBar.ButtonDef] = [
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

        buttonBar = ButtonBar(buttons: buttons, screen: screen, singleScreen: singleScreen)
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
        overlayInfo("WebSocket connected")
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
        if !reconnecting { overlayError("WebSocket not connected") }
        scheduleReconnect()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let _ = error {
            if !reconnecting { overlayError("WebSocket not connected") }
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
                if self?.reconnecting == false { overlayError("WebSocket not connected") }
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
}
