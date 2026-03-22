import AppKit
import Foundation

let app = NSApplication.shared
app.setActivationPolicy(.regular)

// Write PID lock file — newest instance always wins
let pidFilePath = "/tmp/emoji-overlay.pid"
let myPID = ProcessInfo.processInfo.processIdentifier
try? "\(myPID)".write(toFile: pidFilePath, atomically: true, encoding: .utf8)
NSLog("Started with PID \(myPID), wrote lock file")

// Server URL from command line or default
let serverURL: String
if CommandLine.arguments.count > 1 {
    serverURL = CommandLine.arguments[1]
} else {
    serverURL = "ws://localhost:8000"
}

let delegate = AppDelegate(serverURL: serverURL, pidFilePath: pidFilePath, myPID: myPID)
app.delegate = delegate
app.run()
