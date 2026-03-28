import AppKit
import XCTest
@testable import DesktopOverlay

final class ButtonBarSingleScreenTests: XCTestCase {
    func testEdgeTriggerDoesNotActivateOutsideBarVerticalBand() {
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(shownFrame: shownFrame)
        // Mouse within bar X range but above bar Y range → should NOT activate
        XCTAssertFalse(logic.shouldSlideIn(mouse: NSPoint(x: 980, y: 500)))
    }

    func testShownFrameActivatesWhenMouseOverBarPosition() {
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(shownFrame: shownFrame)
        // Mouse exactly at bar's shown position → activate
        XCTAssertTrue(logic.shouldSlideIn(mouse: NSPoint(x: 950, y: 310)))
    }

    func testEdgeTriggerZoneOutsideShownFrameDoesNotActivate() {
        let shownFrame = NSRect(x: 936, y: 200, width: 52, height: 220)
        let logic = SingleScreenHoverLogic(shownFrame: shownFrame)
        // Mouse to the left of shownFrame (outside bar zone) → should NOT activate
        XCTAssertFalse(logic.shouldSlideIn(mouse: NSPoint(x: 880, y: 310)))
    }

    func testSingleScreenAutoHideDelayIsOneSecond() {
        XCTAssertEqual(ButtonBar.singleScreenAutoHideDelay, 1.0, accuracy: 0.001)
    }
}
