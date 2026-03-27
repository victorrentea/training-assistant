import Foundation
import AppKit

/// Persists the button-bar window origin (in global screen coordinates) per monitor-layout fingerprint.
/// Storage: ~/.training-assistants/overlay-positions.json
enum PositionStore {
    private static var filePath: String {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".training-assistants").path
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        return "\(dir)/overlay-positions.json"
    }

    /// Returns the saved button-bar origin for the given fingerprint, or nil if none saved.
    /// Also returns nil if the stored position is not visible on any current screen.
    static func load(fingerprint: String) -> NSPoint? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: filePath)),
              let all  = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Double]],
              let pos  = all[fingerprint],
              let x    = pos["x"], let y = pos["y"] else { return nil }
        let point = NSPoint(x: x, y: y)
        // Sanity check: position must overlap at least one current screen
        let visible = NSScreen.screens.contains { screen in
            screen.frame.insetBy(dx: -50, dy: -50).contains(point)
        }
        guard visible else {
            overlayInfo("Saved position \(Int(x)),\(Int(y)) is off-screen — using default")
            return nil
        }
        return point
    }

    /// Persists the button-bar origin for the given fingerprint.
    static func save(fingerprint: String, origin: NSPoint) {
        var all: [String: [String: Double]] = [:]
        if let data    = try? Data(contentsOf: URL(fileURLWithPath: filePath)),
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Double]] {
            all = existing
        }
        all[fingerprint] = ["x": origin.x, "y": origin.y]
        if let data = try? JSONSerialization.data(withJSONObject: all, options: .prettyPrinted) {
            try? data.write(to: URL(fileURLWithPath: filePath))
        }
        overlayInfo("Saved button bar position \(Int(origin.x)),\(Int(origin.y)) for layout")
    }
}
