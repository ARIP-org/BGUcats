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

        // Scan a cat has its own walk below.
        for (tab, name) in [("Cats", "cats"), ("Profile", "profile")] {
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

    func testScanInLight() {
        scan(look: "light")
    }

    func testScanInDark() {
        scan(look: "dark")
    }

    /// Scan a cat: six photos, two of them from the gallery, sent as one
    /// encounter, with the second photo's upload failing once. What the
    /// made-up server was asked is read back from App info.
    private func scan(look: String) {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting", "-look", look, "-uploadFailsOnce"]
        app.launch()
        openScan(app)
        let take = find(app, "scan.take")
        XCTAssertTrue(take.waitForExistence(timeout: 10), "Scan a cat has no way to take a photo. \(onScreen(app))")
        XCTAssertTrue(find(app, "scan.gallery").exists, "Scan a cat has no way to choose from the gallery. \(onScreen(app))")
        XCTAssertFalse(app.staticTexts["Not built yet"].exists, "Scan a cat still says it is not built.")
        keep(app, "scan-empty-\(look)")

        // Four from the (stand-in) camera, then two from the gallery.
        for taken in 1...4 {
            find(app, "scan.take").tap()
            expect(app, "scan.count", taken == 1 ? "1 photo" : "\(taken) photos")
        }
        find(app, "scan.gallery").tap()
        expect(app, "scan.count", "6 photos")
        XCTAssertEqual(app.staticTexts.matching(identifier: "scan.mark.gallery").count, 2, "The two gallery photos are not marked. \(onScreen(app))")
        keep(app, "scan-photos-\(look)")

        // One can be taken out before sending.
        find(app, "scan.take").tap()
        expect(app, "scan.count", "7 photos")
        find(app, "scan.remove.7").tap()
        expect(app, "scan.count", "6 photos")

        find(app, "scan.send").tap()
        // The second photo's upload fails once: the screen says so in
        // words, and the other five go on.
        let retrying = find(app, "scan.retrying")
        XCTAssertTrue(retrying.waitForExistence(timeout: 15), "A failed upload is not said on screen. \(onScreen(app))")
        expect(app, "scan.progress", "5 of 6 sent", timeout: 7)
        XCTAssertTrue(retrying.label.contains("took too long"), "The screen does not say why it is retrying: \(retrying.label)")
        keep(app, "scan-retrying-\(look)")

        expect(app, "scan.sent", "Sent: 6 photos", timeout: 30)
        XCTAssertFalse(find(app, "scan.retrying").exists, "Sent, and still retrying. \(onScreen(app))")
        keep(app, "scan-sent-\(look)")

        let shown = appInfo(app)
        let record = served(shown)
        XCTAssertEqual(record.first, "encounter place", "The encounter was not asked for first: \(record)")
        for photo in 1...6 {
            let media = record.firstIndex { $0.hasPrefix("media \(photo) ") }
            let upload = record.lastIndex(of: "upload \(photo)")
            let complete = record.firstIndex(of: "complete \(photo)")
            XCTAssertNotNil(media, "Photo \(photo) was never recorded: \(record)")
            XCTAssertNotNil(upload, "Photo \(photo) was never uploaded: \(record)")
            XCTAssertNotNil(complete, "Photo \(photo) was never confirmed: \(record)")
            if let media, let upload, let complete {
                XCTAssertTrue(0 < media && media < upload && upload < complete, "Photo \(photo) went out of order: \(record)")
            }
        }
        XCTAssertTrue(record.contains("upload 2 timed out"), "The made-up failure did not happen: \(record)")
        let started = record.filter { $0.hasPrefix("media ") }
        let gallery = started.filter { $0.contains(" gallery ") }
        XCTAssertEqual(gallery.count, 2, "Not two gallery photos: \(record)")
        XCTAssertTrue(gallery.allSatisfy { $0.hasSuffix(" no-place") }, "A gallery photo carried a place: \(record)")
        XCTAssertTrue(started.filter { $0.contains(" camera ") }.allSatisfy { $0.hasSuffix(" place") }, "A camera photo went without the place: \(record)")

        // The trail says each step by its kind and status, never an id.
        XCTAssertTrue(shown.contains("upload: media 200"), "The trail does not mark the uploads.")
        XCTAssertTrue(shown.contains("upload: retry, timed out"), "The trail does not mark the retry.")
        XCTAssertNil(shown.range(of: "[0-9A-HJKMNP-TV-Z]{26}", options: .regularExpression), "The trail holds an id.")
        app.terminate()
    }

    /// Photos still waiting when the app is closed go at the next launch,
    /// with no tap on Send.
    func testPhotosLeftWaitingGoAtTheNextLaunch() {
        let first = XCUIApplication()
        first.launchArguments = ["-uiTesting", "-look", "light", "-offline"]
        first.launch()
        openScan(first)
        find(first, "scan.take").tap()
        expect(first, "scan.count", "1 photo")
        find(first, "scan.gallery").tap()
        expect(first, "scan.count", "3 photos")
        find(first, "scan.send").tap()
        XCTAssertTrue(find(first, "scan.retrying").waitForExistence(timeout: 15), "With no server, the screen does not say it will retry. \(onScreen(first))")
        first.terminate()

        let second = XCUIApplication()
        second.launchArguments = ["-uiTesting", "-look", "light", "-keepQueue"]
        second.launch()
        // Only looked at: nothing on the Scan screen is tapped.
        openScan(second)
        expect(second, "scan.sent", "Sent: 3 photos", timeout: 30)
        let shown = appInfo(second)
        XCTAssertTrue(shown.contains("upload: 3 waiting from before"), "The second launch did not find the queue.")
        let record = served(shown)
        XCTAssertEqual(record.first, "encounter place", "The encounter was not asked for first: \(record)")
        for photo in 1...3 {
            XCTAssertTrue(record.contains("complete \(photo)"), "Photo \(photo) was not sent at the next launch: \(record)")
        }
        second.terminate()
    }

    private func openScan(_ app: XCUIApplication) {
        let tab = app.tabBars.buttons["Scan a cat"]
        XCTAssertTrue(tab.waitForExistence(timeout: 30), "The tabs did not open. \(onScreen(app))")
        tab.tap()
        XCTAssertTrue(app.navigationBars["Scan a cat"].waitForExistence(timeout: 10), "Scan a cat did not open.")
    }

    private func find(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    /// Waits for an element to say exactly `label`.
    private func expect(_ app: XCUIApplication, _ id: String, _ label: String, timeout: TimeInterval = 10) {
        let element = find(app, id)
        let said = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", label), object: element)
        XCTAssertEqual(XCTWaiter().wait(for: [said], timeout: timeout), .completed, "\(id) does not say \"\(label)\". \(onScreen(app))")
    }

    /// Profile, then App info: its whole text.
    private func appInfo(_ app: XCUIApplication) -> String {
        app.tabBars.buttons["Profile"].tap()
        let row = find(app, "row.app-info")
        XCTAssertTrue(row.waitForExistence(timeout: 10), "Profile has no App info row.")
        row.tap()
        let text = find(app, "app-info.text")
        XCTAssertTrue(text.waitForExistence(timeout: 10), "App info did not open.")
        return text.label + "\n" + (text.value as? String ?? "")
    }

    /// What the made-up server was asked, from App info, in order.
    private func served(_ shown: String) -> [String] {
        guard let part = shown.components(separatedBy: "stand-in server:\n").dropFirst().first else { return [] }
        // The label and the value may both hold the text: the first copy.
        return Array(part.components(separatedBy: "\n").prefix { !$0.isEmpty && !$0.hasPrefix("BGU Cats, app info") })
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
