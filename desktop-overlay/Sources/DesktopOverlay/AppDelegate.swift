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
        guard let screen = NSScreen.main ?? NSScreen.screens.first else {
            fatalError("No screens available")
        }

        overlayPanel = OverlayPanel(screen: screen)
        overlayPanel.orderFrontRegardless()

        guard let hostLayer = overlayPanel.contentView?.layer else {
            fatalError("Content view has no layer")
        }
        animator = EmojiAnimator(hostLayer: hostLayer)

        session = URLSession(configuration: .default, delegate: self, delegateQueue: .main)
        connectWebSocket()
        setupButtonBar(screen: screen)

        // Check every 2s if another instance took over the PID file
        pidCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.checkPIDFile()
        }
    }

    // MARK: - Button bar

    private func setupButtonBar(screen: NSScreen) {
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

        buttonBar = ButtonBar(buttons: buttons, screen: screen)
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
