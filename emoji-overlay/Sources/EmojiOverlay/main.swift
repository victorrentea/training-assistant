import AppKit
import Foundation

// --- PID lock file: ensure only one instance runs at a time ---
let lockFilePath = "/tmp/EmojiOverlay.pid"
let myPid = getpid()

// Write our PID immediately (supersedes any previous instance)
try? "\(myPid)".write(toFile: lockFilePath, atomically: true, encoding: .utf8)
NSLog("EmojiOverlay: started with PID %d, wrote lock file", myPid)

// Clean up lock file on exit (only if we still own it)
func cleanupLockFile() {
    if let pidStr = try? String(contentsOfFile: lockFilePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
       let pid = Int32(pidStr),
       pid == myPid {
        try? FileManager.default.removeItem(atPath: lockFilePath)
    }
}
atexit { cleanupLockFile() }

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

// Periodic self-check: exit if another instance has taken over the lock file
Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in
    guard let pidStr = try? String(contentsOfFile: lockFilePath, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines),
          let filePid = Int32(pidStr) else {
        return // lock file missing or unreadable — keep running
    }
    if filePid != myPid {
        NSLog("EmojiOverlay: PID %d superseded by PID %d — exiting", myPid, filePid)
        cleanupLockFile()
        NSApplication.shared.terminate(nil)
    }
}

app.run()
