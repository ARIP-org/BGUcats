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
/// picture. `-signedOut` starts it with nobody signed in; `-termsRequired`
/// with the terms not accepted, `-termsChanged` with terms that changed
/// after the account was read. `-look` names the look
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

        // The terms not accepted yet: the first like asks for them, in the
        // system's dialog over the feed, before anything is sent.
        let asking = XCUIApplication()
        asking.launchArguments = ["-uiTesting", "-look", look, "-termsRequired"]
        asking.launch()
        let mitzi = asking.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(mitzi.waitForExistence(timeout: 30), "The feed did not show its first post. \(onScreen(asking))")
        XCTAssertEqual(mitzi.label, "Like, 3")
        mitzi.tap()
        let terms = asking.alerts["Before you post"]
        XCTAssertTrue(terms.waitForExistence(timeout: 10), "A like before the terms did not ask for them. \(onScreen(asking))")
        XCTAssertTrue(terms.buttons["Accept and go on"].exists, "The terms' dialog has no way to accept. \(onScreen(asking))")
        keep(asking, "terms-\(look)")

        // "Cancel": nothing is sent, and the like is not counted.
        terms.buttons["Cancel"].tap()
        XCTAssertTrue(gone(terms), "The terms' dialog stayed after Cancel.")
        XCTAssertEqual(mitzi.value as? String, "not liked", "A declined like was counted.")
        XCTAssertEqual(mitzi.label, "Like, 3", "A declined like changed the count.")

        // Asked again at the next like; accepting lets the like through.
        mitzi.tap()
        XCTAssertTrue(terms.waitForExistence(timeout: 10), "The next like did not ask for the terms again. \(onScreen(asking))")
        terms.buttons["Accept and go on"].tap()
        let counted = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [counted], timeout: 10), .completed, "After accepting the terms the like was not counted. \(onScreen(asking))")
        XCTAssertEqual(mitzi.value as? String, "liked")

        // Accepted once: taking the like back and liking again asks nothing.
        mitzi.tap()
        let undone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 3"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [undone], timeout: 10), .completed, "Taking the like back did not count. \(onScreen(asking))")
        mitzi.tap()
        XCTAssertFalse(asking.alerts.firstMatch.waitForExistence(timeout: 2), "A like after the terms were accepted asked again. \(onScreen(asking))")
        let again = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [again], timeout: 10), .completed, "The second like was not counted. \(onScreen(asking))")

        // The trail says what was asked and answered, never who.
        asking.tabBars.buttons["Profile"].tap()
        let info = asking.descendants(matching: .any)["row.app-info"].firstMatch
        XCTAssertTrue(info.waitForExistence(timeout: 10), "Profile has no App info row.")
        info.tap()
        let told = asking.descendants(matching: .any)["app-info.text"].firstMatch
        XCTAssertTrue(told.waitForExistence(timeout: 10), "App info did not open.")
        let lines = told.label + "\n" + (told.value as? String ?? "")
        for line in ["terms: asked", "terms: declined", "terms: accepted"] {
            XCTAssertTrue(lines.contains(line), "App info did not keep \"\(line)\".")
        }
        asking.terminate()

        // The terms changed after the account was read: the server refuses
        // the like, and the app asks once more instead of showing its word.
        let changed = XCUIApplication()
        changed.launchArguments = ["-uiTesting", "-look", look, "-termsChanged"]
        changed.launch()
        let late = changed.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(late.waitForExistence(timeout: 30), "The feed did not show its first post. \(onScreen(changed))")
        late.tap()
        let asked = changed.alerts["Before you post"]
        XCTAssertTrue(asked.waitForExistence(timeout: 10), "A like refused for the terms did not ask for them. \(onScreen(changed))")
        asked.buttons["Accept and go on"].tap()
        let through = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: late)
        XCTAssertEqual(XCTWaiter().wait(for: [through], timeout: 10), .completed, "After accepting the changed terms the like was not counted. \(onScreen(changed))")
        XCTAssertFalse(changed.alerts["That did not work"].exists, "The server's refusal was shown. \(onScreen(changed))")
        changed.terminate()

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
        keep(app, "app-info-\(look)")

        let copy = app.descendants(matching: .any)["app-info.copy"].firstMatch
        copy.tap()
        XCTAssertTrue(app.buttons["Copied"].waitForExistence(timeout: 5), "Copying did not say it copied.")

        app.terminate()
    }

    /// What is on screen, in one line, for a failure's message: nobody
    /// here can open the simulator, so the job's log is all there is.
    private func onScreen(_ app: XCUIApplication) -> String {
        let texts = app.staticTexts.allElementsBoundByIndex.prefix(20).map { $0.label }
        let buttons = app.buttons.allElementsBoundByIndex.prefix(20).map { "\($0.identifier)=\($0.label)" }
        return "On screen, texts: \(texts); buttons: \(buttons)"
    }

    /// The element is gone within a few seconds.
    private func gone(_ element: XCUIElement) -> Bool {
        let away = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: element)
        return XCTWaiter().wait(for: [away], timeout: 5) == .completed
    }

    private func keep(_ app: XCUIApplication, _ name: String) {
        let shot = app.screenshot()
        let picture = XCTAttachment(screenshot: shot)
        picture.name = name
        picture.lifetime = .keepAlways
        add(picture)
        // A picture named dark is dark, and one named light is light. Under
        // a system dialog iOS dims the screen behind it by about a fifth,
        // so a light one's bar is lowered by as much; still far above dark.
        let bright = ScreensUITests.brightness(shot.image)
        let light = name.hasPrefix("terms-") ? 0.52 : 0.65
        if name.hasSuffix("-dark") {
            XCTAssertLessThan(bright, 0.35, "\(name) is not dark: the screen's brightness is \(bright).")
        } else {
            XCTAssertGreaterThan(bright, light, "\(name) is not light: the screen's brightness is \(bright).")
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
