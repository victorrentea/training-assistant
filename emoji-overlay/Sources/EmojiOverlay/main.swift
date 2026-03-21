import AppKit
import Foundation

// --- PID lock file: ensure only one instance runs at a time ---
let lockFilePath = "/tmp/EmojiOverlay.pid"

// Kill any previous instance
if let existingPidStr = try? String(contentsOfFile: lockFilePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
   let existingPid = Int32(existingPidStr),
   existingPid != getpid() {
    if kill(existingPid, 0) == 0 {
        NSLog("EmojiOverlay: killing previous instance (PID %d)", existingPid)
        kill(existingPid, SIGTERM)
        // Brief wait for it to exit
        usleep(200_000) // 200ms
        // Force kill if still alive
        if kill(existingPid, 0) == 0 {
            kill(existingPid, SIGKILL)
        }
    }
}

// Write our PID
try? "\(getpid())".write(toFile: lockFilePath, atomically: true, encoding: .utf8)

// Clean up lock file on exit
func cleanupLockFile() {
    if let pidStr = try? String(contentsOfFile: lockFilePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
       let pid = Int32(pidStr),
       pid == getpid() {
        try? FileManager.default.removeItem(atPath: lockFilePath)
    }
}
atexit { cleanupLockFile() }
signal(SIGTERM) { _ in cleanupLockFile(); exit(0) }
signal(SIGINT) { _ in cleanupLockFile(); exit(0) }

// --- Normal startup ---
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
