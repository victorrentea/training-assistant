import Foundation

// Shared log formatter — matches daemon/log.py format:
//   HH:MM:SS.f  PID  [name      ] info    message
//   HH:MM:SS.f  PID  [name      ] error   message
//
// Example:
//   18:49:42.1 66445  [overlay   ] info    WebSocket connected
//   18:49:55.3 66445  [overlay   ] error   WebSocket not connected

private let _pid = Int(ProcessInfo.processInfo.processIdentifier)
// name = "overlay" (7 chars), padded to 10
private let _name = "overlay   "

func overlayInfo(_ msg: String) { _overlayLog("info", msg) }
func overlayError(_ msg: String) { _overlayLog("error", msg) }

private func _overlayLog(_ level: String, _ msg: String) {
    let now = Date()
    let c = Calendar.current
    let h = c.component(.hour, from: now)
    let m = c.component(.minute, from: now)
    let s = c.component(.second, from: now)
    let f = c.component(.nanosecond, from: now) / 100_000_000
    let ts = String(format: "%02d:%02d:%02d.%d", h, m, s, f)
    // "info    " and "error   " both = 8 display cols → message column always aligned
    let lvl = level == "error" ? "error   " : "info    "
    let line = "\(ts) \(String(format: "%5d", _pid))  [\(_name)] \(lvl)\(msg)"
    if level == "error" {
        let stderr = FileHandle.standardError
        stderr.write((line + "\n").data(using: .utf8)!)
    } else {
        print(line)
    }
}
