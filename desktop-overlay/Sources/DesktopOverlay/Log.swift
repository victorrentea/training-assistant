import Foundation

// Shared log formatter — matches daemon/log.py format:
//   [overlay   ] HH:MM:SS.f info    message
//   [overlay   ] HH:MM:SS.f error❌ message

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
    let lvl = level == "error" ? "error❌" : "info   "
    let line = "[overlay   ] \(ts) \(lvl) \(msg)"
    if level == "error" {
        let stderr = FileHandle.standardError
        stderr.write((line + "\n").data(using: .utf8)!)
    } else {
        print(line)
    }
}
