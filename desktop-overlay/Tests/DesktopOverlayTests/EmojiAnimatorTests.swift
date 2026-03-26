import XCTest
@testable import DesktopOverlay

final class EmojiAnimatorTests: XCTestCase {
    func testTvEmojiUsesBreakingGlassSound() {
        XCTAssertEqual(EmojiAnimator.soundEffect(for: "📺"), "breaking-glass.mp3")
    }

    func testHeartEmojiHasNoSoundEffect() {
        XCTAssertNil(EmojiAnimator.soundEffect(for: "❤️"))
    }

    func testBreakingGlassResourceIsBundled() {
        let url = Bundle.module.url(forResource: "breaking-glass.mp3", withExtension: nil, subdirectory: "Resources")
        XCTAssertNotNil(url)
    }
}
