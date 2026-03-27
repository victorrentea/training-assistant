import AppKit
import CoreGraphics

/// Computes a stable string key that uniquely identifies the current monitor layout.
/// Two sessions with the same monitors connected in the same arrangement produce the same key.
enum ScreenFingerprint {
    static func current() -> String {
        let keys: [String] = NSScreen.screens.map { screen in
            guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID else {
                return "unk:\(Int(screen.frame.minX)),\(Int(screen.frame.minY)):\(Int(screen.frame.width))x\(Int(screen.frame.height))"
            }
            let vendor = CGDisplayVendorNumber(number)
            let model  = CGDisplayModelNumber(number)
            let serial = CGDisplaySerialNumber(number)
            // Include frame origin so rearranging monitors produces a different fingerprint
            let ox = Int(screen.frame.minX)
            let oy = Int(screen.frame.minY)
            let w  = Int(screen.frame.width)
            let h  = Int(screen.frame.height)
            return "\(vendor):\(model):\(serial):\(ox),\(oy):\(w)x\(h)"
        }.sorted()
        return keys.joined(separator: "|")
    }
}
