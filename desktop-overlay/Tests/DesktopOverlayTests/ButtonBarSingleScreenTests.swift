import AppKit
import XCTest
@testable import DesktopOverlay

final class ButtonBarSingleScreenTests: XCTestCase {
    func testEdgeTriggerDoesNotActivateOutsideBarVerticalBand() {
        let hiddenFrame = NSRect(x: 1000, y: 200, width: 52, height: 220)
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(
            hiddenFrame: hiddenFrame,
            shownFrame: shownFrame,
            edgeTriggerDistance: 80,
            onBarInset: 20
        )

        XCTAssertFalse(logic.shouldSlideIn(mouse: NSPoint(x: 980, y: 500)))
    }

    func testEdgeTriggerActivatesInsideBarVerticalBand() {
        let hiddenFrame = NSRect(x: 1000, y: 200, width: 52, height: 220)
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(
            hiddenFrame: hiddenFrame,
            shownFrame: shownFrame,
            edgeTriggerDistance: 80,
            onBarInset: 20
        )

        XCTAssertTrue(logic.shouldSlideIn(mouse: NSPoint(x: 980, y: 260)))
    }

    func testSingleScreenAutoHideDelayIsOneSecond() {
        XCTAssertEqual(ButtonBar.singleScreenAutoHideDelay, 1.0, accuracy: 0.001)
    }
}
