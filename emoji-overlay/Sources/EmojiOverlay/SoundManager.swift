import AVFoundation
import Foundation

/// Manages sound effects for overlay effects. Supports overlapping plays of the same sound.
/// All operations run on the main thread (AVAudioPlayer is not thread-safe).
class SoundManager {
    static let shared = SoundManager()

    private var players: [String: [AVAudioPlayer]] = [:]

    private init() {}

    /// Play a sound from the bundle Resources folder.
    /// Each call creates a new player, allowing overlapping playback of the same sound.
    func play(_ filename: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            guard let url = Bundle.module.url(forResource: filename, withExtension: nil, subdirectory: "Resources") else {
                NSLog("SoundManager: file not found: \(filename)")
                return
            }

            do {
                let player = try AVAudioPlayer(contentsOf: url)
                player.volume = 1.0
                player.prepareToPlay()
                if self.players[filename] == nil {
                    self.players[filename] = []
                }
                self.players[filename]!.append(player)
                player.play()
            } catch {
                NSLog("SoundManager: failed to play \(filename): \(error)")
            }
        }
    }

    /// Fade out all active players for this sound over 300ms then stop.
    func stop(_ filename: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, let activePlayers = self.players[filename] else {
                return
            }
            let playing = activePlayers.filter { $0.isPlaying }
            if playing.isEmpty {
                self.players[filename] = nil
                return
            }
            for player in playing {
                player.setVolume(0, fadeDuration: 0.3)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                for player in playing {
                    player.stop()
                }
                // Remove stopped players, keep any new ones that started after stop was called
                self?.players[filename]?.removeAll { p in playing.contains(where: { $0 === p }) }
                if self?.players[filename]?.isEmpty == true {
                    self?.players[filename] = nil
                }
            }
        }
    }
}
