import AVFoundation
import Foundation

/// Manages sound effects for overlay effects. Prevents overlapping plays of the same sound.
/// All operations run on the main thread (AVAudioPlayer is not thread-safe).
class SoundManager {
    static let shared = SoundManager()

    private var players: [String: AVAudioPlayer] = [:]

    private init() {}

    /// Play a sound from the bundle Resources folder.
    /// If the same sound is already playing, does nothing (no restart).
    func play(_ filename: String) {
        DispatchQueue.main.async { [weak self] in
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
                player.volume = 1.0
                player.prepareToPlay()
                self.players[filename] = player
                player.play()
            } catch {
                NSLog("SoundManager: failed to play \(filename): \(error)")
            }
        }
    }

    /// Fade out over 300ms then stop. Called when the animation finishes —
    /// the sound continues playing (fading) for 300ms after the visual ends.
    func stop(_ filename: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, let player = self.players[filename], player.isPlaying else {
                self?.players[filename] = nil
                return
            }
            player.setVolume(0, fadeDuration: 0.3)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                player.stop()
                self?.players[filename] = nil
            }
        }
    }
}
