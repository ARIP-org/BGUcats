import UIKit
import XCTest

/// Opens every screen in a simulator and keeps a picture of each, in light
/// and in dark: the same job tests/web does for the web app. Swift cannot be
/// compiled on Linux, so this run on a Mac is how anyone, an agent or a
/// person, sees a screen before it is merged.
///
/// The app is started with `-uiTesting`: it reads nothing from the network
/// and keeps nothing on the phone, its member and its posts are made up,
/// and its clock stands still, so two pictures of one screen are the same
/// picture. `-signedOut` starts it with nobody signed in. `-look` names the look
/// to draw, and every picture is checked to be that look: on this job's
/// first run all ten came out light and nothing noticed.
final class ScreensUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testEveryScreenInLight() {
        walk(look: "light")
    }

    func testEveryScreenInDark() {
        walk(look: "dark")
    }

    private func walk(look: String) {
        // Nobody signed in: the sign-in screen, with its one button. The
        // sheet behind it is Google's and is not opened here.
        let signedOut = XCUIApplication()
        signedOut.launchArguments = ["-uiTesting", "-look", look, "-signedOut"]
        signedOut.launch()
        let google = signedOut.descendants(matching: .any)["sign-in.google"].firstMatch
        XCTAssertTrue(google.waitForExistence(timeout: 30), "With nobody signed in, the app did not show the sign-in screen.")
        XCTAssertTrue(signedOut.buttons["App info"].exists, "The sign-in screen has no way to App info.")
        keep(signedOut, "sign-in-\(look)")
        signedOut.terminate()

        // A sign-in that ends while the app is open (the server refuses
        // the token): the sign-in screen comes up and says why, instead of
        // a feed whose every tap fails.
        let ending = XCUIApplication()
        ending.launchArguments = ["-uiTesting", "-look", look, "-signInEnds"]
        ending.launch()
        let heart = ending.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(heart.waitForExistence(timeout: 30), "The feed did not show its first post. \(onScreen(ending))")
        heart.tap()
        let again = ending.descendants(matching: .any)["sign-in.google"].firstMatch
        XCTAssertTrue(again.waitForExistence(timeout: 15), "The sign-in ended and the sign-in screen did not come up. \(onScreen(ending))")
        XCTAssertTrue(ending.staticTexts["Your sign-in ended. Sign in again."].exists, "The sign-in screen does not say why it is there. \(onScreen(ending))")
        keep(ending, "sign-in-ended-\(look)")
        ending.terminate()

        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting", "-look", look]
        app.launch()

        // Signed in, it opens on Home: the feed.
        XCTAssertTrue(app.navigationBars["Home"].waitForExistence(timeout: 30), "The app did not open on Home.")
        let first = app.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 15), "The feed did not show its first post. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["By the library steps again, asleep in the sun."].exists, "The first post's words are not on screen. \(onScreen(app))")
        keep(app, "home-\(look)")

        // A like counts at once and stays.
        XCTAssertEqual(first.value as? String, "not liked")
        first.tap()
        let liked = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "liked"), object: first)
        XCTAssertEqual(XCTWaiter().wait(for: [liked], timeout: 10), .completed, "Tapping the heart did not like the post.")
        keep(app, "home-liked-\(look)")

        // A post's menu. On the member's own post (the second): Delete,
        // with the system's confirmation; the card leaves the feed.
        let own = app.descendants(matching: .any)["menu.p2"].firstMatch
        reveal(own, in: app)
        own.tap()
        let delete = app.buttons["Delete post"].firstMatch
        XCTAssertTrue(delete.waitForExistence(timeout: 10), "The menu on one's own post has no Delete. \(onScreen(app))")
        XCTAssertFalse(app.buttons["Report"].exists, "The menu on one's own post offers Report. \(onScreen(app))")
        keep(app, "post-menu-own-\(look)")
        delete.tap()
        let confirm = app.alerts.buttons["Delete"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "Delete did not ask first. \(onScreen(app))")
        confirm.tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: own)
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 10), .completed, "The deleted post is still in the feed. \(onScreen(app))")
        // Two cards are left: the first and the third.
        reveal(app.descendants(matching: .any)["menu.p1"].firstMatch, in: app)
        let other = app.descendants(matching: .any)["menu.p3"].firstMatch
        reveal(other, in: app)
        XCTAssertFalse(app.descendants(matching: .any)["like.p2"].firstMatch.exists, "The deleted post came back. \(onScreen(app))")

        // On anyone else's: Report, a sheet with the six reasons, and thanks.
        other.tap()
        let report = app.buttons["Report"].firstMatch
        XCTAssertTrue(report.waitForExistence(timeout: 10), "The menu on another's post has no Report. \(onScreen(app))")
        XCTAssertFalse(app.buttons["Delete post"].exists, "The menu on another's post offers Delete. \(onScreen(app))")
        keep(app, "post-menu-other-\(look)")
        report.tap()
        for reason in ["spam", "offensive", "harassment", "privacy", "not_cat", "other"] {
            let row = app.descendants(matching: .any)["reason.\(reason)"].firstMatch
            XCTAssertTrue(row.waitForExistence(timeout: 10), "The report sheet has no reason \(reason). \(onScreen(app))")
        }
        let send = app.descendants(matching: .any)["report.send"].firstMatch
        XCTAssertFalse(send.isEnabled, "A report can be sent with no reason.")
        keep(app, "report-\(look)")
        app.descendants(matching: .any)["reason.spam"].firstMatch.tap()
        XCTAssertTrue(send.isEnabled, "Choosing a reason did not let the report go.")
        send.tap()
        let thanks = app.descendants(matching: .any)["report.thanks"].firstMatch
        XCTAssertTrue(thanks.waitForExistence(timeout: 10), "Sending a report did not say thank you. \(onScreen(app))")
        app.descendants(matching: .any)["report.done"].firstMatch.tap()
        XCTAssertTrue(thanks.waitForNonExistence(timeout: 10), "Done did not close the report. \(onScreen(app))")

        for (tab, name) in [("Cats", "cats"), ("Scan a cat", "scan"), ("Profile", "profile")] {
            app.tabBars.buttons[tab].tap()
            XCTAssertTrue(app.navigationBars[tab].waitForExistence(timeout: 10), "The tab \(tab) did not open.")
            keep(app, "\(name)-\(look)")
        }

        // Profile says who is signed in.
        XCTAssertTrue(app.staticTexts["Test Member"].exists || app.descendants(matching: .any)["profile.me"].firstMatch.exists, "Profile does not say who is signed in.")
        XCTAssertTrue(app.descendants(matching: .any)["profile.sign-out"].firstMatch.exists, "Profile has no way to sign out.")

        // Profile, then "App info".
        let row = app.descendants(matching: .any)["row.app-info"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10), "Profile has no App info row.")
        row.tap()
        let text = app.descendants(matching: .any)["app-info.text"].firstMatch
        XCTAssertTrue(text.waitForExistence(timeout: 10), "App info did not open.")
        // Selectable text may be read out as a value, not a label.
        let shown = text.label + "\n" + (text.value as? String ?? "")
        XCTAssertTrue(shown.contains("kind: iPhone app (Swift)"), "App info does not say what kind of app this is.")
        XCTAssertTrue(shown.contains("start: ready"), "App info does not show what the app was doing.")
        XCTAssertTrue(shown.contains("tab: profile"), "App info did not keep the tab that was opened.")
        XCTAssertTrue(shown.contains("feed: 3 posts"), "App info did not keep that the feed was read.")
        XCTAssertTrue(shown.contains("post: deleted"), "App info did not keep that a post was deleted.")
        XCTAssertTrue(shown.contains("report: sent (spam)"), "App info did not keep that a report was sent.")
        XCTAssertFalse(shown.contains("p2") || shown.contains("p3"), "App info names a post.")
        keep(app, "app-info-\(look)")

        let copy = app.descendants(matching: .any)["app-info.copy"].firstMatch
        copy.tap()
        XCTAssertTrue(app.buttons["Copied"].waitForExistence(timeout: 5), "Copying did not say it copied.")

        app.terminate()
    }

    /// Scrolls the feed until the element can be tapped: down first, then
    /// back up if it went past.
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<6 where !(element.exists && element.isHittable) {
            app.swipeUp(velocity: .slow)
        }
        for _ in 0..<6 where !(element.exists && element.isHittable) {
            app.swipeDown(velocity: .slow)
        }
        XCTAssertTrue(element.exists && element.isHittable, "\(element) cannot be reached. \(onScreen(app))")
    }

    /// What is on screen, in one line, for a failure's message: nobody
    /// here can open the simulator, so the job's log is all there is.
    private func onScreen(_ app: XCUIApplication) -> String {
        let texts = app.staticTexts.allElementsBoundByIndex.prefix(20).map { $0.label }
        let buttons = app.buttons.allElementsBoundByIndex.prefix(20).map { "\($0.identifier)=\($0.label)" }
        return "On screen, texts: \(texts); buttons: \(buttons)"
    }

    private func keep(_ app: XCUIApplication, _ name: String) {
        let shot = app.screenshot()
        let picture = XCTAttachment(screenshot: shot)
        picture.name = name
        picture.lifetime = .keepAlways
        add(picture)
        // A picture named dark is dark, and one named light is light.
        let bright = ScreensUITests.brightness(shot.image)
        if name.hasSuffix("-dark") {
            XCTAssertLessThan(bright, 0.35, "\(name) is not dark: the screen's brightness is \(bright).")
        } else {
            XCTAssertGreaterThan(bright, 0.65, "\(name) is not light: the screen's brightness is \(bright).")
        }
    }

    /// How bright a picture is as a whole, from 0 (black) to 1 (white):
    /// the picture drawn into a single pixel.
    private static func brightness(_ image: UIImage) -> Double {
        guard let source = image.cgImage else { return -1 }
        var pixel = [UInt8](repeating: 0, count: 4)
        pixel.withUnsafeMutableBytes { bytes in
            let context = CGContext(
                data: bytes.baseAddress,
                width: 1,
                height: 1,
                bitsPerComponent: 8,
                bytesPerRow: 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            )
            context?.interpolationQuality = .high
            context?.draw(source, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        }
        return (Double(pixel[0]) + Double(pixel[1]) + Double(pixel[2])) / (3 * 255)
    }
}
