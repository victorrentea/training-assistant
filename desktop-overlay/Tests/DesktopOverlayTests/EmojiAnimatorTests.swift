import Foundation
import XCTest
@testable import DesktopOverlay

final class EmojiAnimatorTests: XCTestCase {
    func testScreenEmojiUsesBreakingGlassSound() {
        XCTAssertEqual(EmojiAnimator.soundFilename(for: "🖥️"), "breaking-glass.mp3")
        XCTAssertNil(EmojiAnimator.soundFilename(for: "❤️"))
    }

    func testBreakingGlassResourceExistsInBundle() {
        let url = Bundle.module.url(forResource: "breaking-glass.mp3", withExtension: nil, subdirectory: "Resources")
        XCTAssertNotNil(url)
    }
}
