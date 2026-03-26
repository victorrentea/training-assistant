import CoreGraphics
import XCTest
@testable import DesktopOverlay

final class ScreenTopologyTests: XCTestCase {
    func testSingleDisplayHasNoSecondaryDesktop() {
        let frames = [
            CGRect(x: 0, y: 0, width: 1728, height: 1117),
        ]

        XCTAssertFalse(ScreenTopology.hasSecondaryDesktop(frames: frames))
        XCTAssertEqual(ScreenTopology.preferredButtonScreenIndex(frames: frames), 0)
    }

    func testMirroredDisplayHasNoSecondaryDesktop() {
        let frames = [
            CGRect(x: 0, y: 0, width: 1728, height: 1117), // primary
            CGRect(x: 0, y: 0, width: 1728, height: 1117), // mirror
        ]

        XCTAssertFalse(ScreenTopology.hasSecondaryDesktop(frames: frames))
        XCTAssertEqual(ScreenTopology.preferredButtonScreenIndex(frames: frames), 0)
    }

    func testExtendedDisplayAboveIsPreferredForButtonBar() {
        let frames = [
            CGRect(x: 0, y: 0, width: 1728, height: 1117), // primary
            CGRect(x: 0, y: 1120, width: 1920, height: 1080), // external above
        ]

        XCTAssertTrue(ScreenTopology.hasSecondaryDesktop(frames: frames))
        XCTAssertEqual(ScreenTopology.preferredButtonScreenIndex(frames: frames), 1)
    }
}
