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

    func testShownFrameActivatesWhenMouseOverBarPosition() {
        let hiddenFrame = NSRect(x: 1000, y: 200, width: 52, height: 220)
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(
            hiddenFrame: hiddenFrame,
            shownFrame: shownFrame,
            edgeTriggerDistance: 80,
            onBarInset: 20
        )
        // Mouse exactly at bar's shown position → activate
        XCTAssertTrue(logic.shouldSlideIn(mouse: NSPoint(x: 950, y: 310)))
    }

    func testEdgeTriggerZoneOutsideShownFrameDoesNotActivate() {
        let hiddenFrame = NSRect(x: 1000, y: 200, width: 52, height: 220)
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(
            hiddenFrame: hiddenFrame,
            shownFrame: shownFrame,
            edgeTriggerDistance: 80,
            onBarInset: 20
        )
        // Mouse to the left of shownFrame (outside bar zone) → should NOT activate
        XCTAssertFalse(logic.shouldSlideIn(mouse: NSPoint(x: 880, y: 310)))
    }

    func testSingleScreenAutoHideDelayIsOneSecond() {
        XCTAssertEqual(ButtonBar.singleScreenAutoHideDelay, 1.0, accuracy: 0.001)
    }
}
