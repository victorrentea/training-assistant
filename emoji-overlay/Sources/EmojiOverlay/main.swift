import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.regular)

// Server URL from command line or default
let serverURL: String
if CommandLine.arguments.count > 1 {
    serverURL = CommandLine.arguments[1]
} else {
    serverURL = "ws://localhost:8000"
}

let delegate = AppDelegate(serverURL: serverURL)
app.delegate = delegate
app.run()
