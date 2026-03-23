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
        overlayPanel = OverlayPanel()
        overlayPanel.orderFrontRegardless()

        guard let hostLayer = overlayPanel.contentView?.layer else {
            fatalError("Content view has no layer")
        }
        animator = EmojiAnimator(hostLayer: hostLayer)

        session = URLSession(configuration: .default, delegate: self, delegateQueue: .main)
        connectWebSocket()
        registerGlobalHotkeys()
        setupButtonBar()


        // Check every 2s if another instance took over the PID file
        pidCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.checkPIDFile()
        }
    }

    // MARK: - Button bar

    private func setupButtonBar() {
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
            .init(label: "⚔️", tooltip: "Zorro") { [weak self] in
                self?.animator.showZorro()
            },
        ]

        buttonBar = ButtonBar(buttons: buttons)
        buttonBar.orderFrontRegardless()
    }

    // MARK: - Global hotkeys

    private func registerGlobalHotkeys() {
        // Cmd+Shift+K → confetti burst
        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            // Cmd+Shift+K (keyCode 40 = K)
            if flags == [.command, .shift] && event.keyCode == 40 {
                self?.animator.spawnConfetti()
            }
        }
        // Also catch when our app is focused (unlikely but safe)
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            if flags == [.command, .shift] && event.keyCode == 40 {
                self?.animator.spawnConfetti()
                return nil
            }
            return event
        }
        NSLog("Global hotkey registered: Cmd+Shift+K → confetti")
    }

    private func checkPIDFile() {
        guard let content = try? String(contentsOfFile: pidFilePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
              let filePID = Int32(content) else {
            return
        }
        if filePID != myPID {
            NSLog("Another instance (PID \(filePID)) took over — shutting down (my PID: \(myPID))")
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
            NSLog("Invalid server URL: \(serverURL)")
            return
        }
        NSLog("Connecting to \(url)...")
        wsTask = session.webSocketTask(with: url)
        wsTask?.resume()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        NSLog("WebSocket connected")
        // Send set_name as required by protocol
        let msg = "{\"type\":\"set_name\",\"name\":\"Overlay\"}"
        wsTask?.send(.string(msg)) { error in
            if let error = error {
                NSLog("Failed to send set_name: \(error)")
            }
        }
        receiveMessage()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        NSLog("WebSocket closed (code: \(closeCode.rawValue)), reconnecting in 3s...")
        scheduleReconnect()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            NSLog("WebSocket transport error: \(error.localizedDescription), reconnecting in 3s...")
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
            case .failure(let error):
                NSLog("WebSocket receive error: \(error), reconnecting...")
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
