import AVFoundation
import Foundation

/// Manages sound effects for overlay effects. Prevents overlapping plays of the same sound.
class SoundManager {
    static let shared = SoundManager()

    private var players: [String: AVAudioPlayer] = [:]
    private let queue = DispatchQueue(label: "sound-manager")

    private init() {}

    /// Play a sound from the bundle Resources folder.
    /// If the same sound is already playing, does nothing (no restart).
    func play(_ filename: String) {
        queue.async { [weak self] in
            guard let self = self else { return }

            // Already playing? Skip.
            if let existing = self.players[filename], existing.isPlaying {
                return
            }

            guard let url = Bundle.module.url(forResource: filename, withExtension: nil, subdirectory: "Resources") else {
                NSLog("SoundManager: file not found: \(filename)")
                return
            }

            do {
                let player = try AVAudioPlayer(contentsOf: url)
                player.prepareToPlay()
                self.players[filename] = player
                DispatchQueue.main.async {
                    player.play()
                }
            } catch {
                NSLog("SoundManager: failed to play \(filename): \(error)")
            }
        }
    }

    /// Stop a currently playing sound.
    func stop(_ filename: String) {
        queue.async { [weak self] in
            self?.players[filename]?.stop()
            self?.players[filename] = nil
        }
    }

    /// Check if a sound is currently playing.
    func isPlaying(_ filename: String) -> Bool {
        return players[filename]?.isPlaying ?? false
    }
}
