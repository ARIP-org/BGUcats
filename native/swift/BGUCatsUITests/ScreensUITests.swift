import XCTest

/// Opens every screen in a simulator and keeps a picture of each, in light
/// and in dark: the same job tests/web does for the web app. Swift cannot be
/// compiled on Linux, so this run on a Mac is how anyone, an agent or a
/// person, sees a screen before it is merged.
///
/// The app is started with `-uiTesting`: it reads nothing from the network
/// and keeps nothing on the phone, and its clock stands still, so two
/// pictures of one screen are the same picture.
final class ScreensUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    override func tearDown() {
        XCUIDevice.shared.appearance = .light
    }

    func testEveryScreenInLight() {
        walk(look: "light", appearance: .light)
    }

    func testEveryScreenInDark() {
        walk(look: "dark", appearance: .dark)
    }

    private func walk(look: String, appearance: XCUIDevice.Appearance) {
        XCUIDevice.shared.appearance = appearance
        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting"]
        app.launch()

        // It opens on Home.
        XCTAssertTrue(app.navigationBars["Home"].waitForExistence(timeout: 30), "The app did not open on Home.")
        keep(app, "home-\(look)")

        for (tab, name) in [("Cats", "cats"), ("Scan a cat", "scan"), ("Profile", "profile")] {
            app.tabBars.buttons[tab].tap()
            XCTAssertTrue(app.navigationBars[tab].waitForExistence(timeout: 10), "The tab \(tab) did not open.")
            keep(app, "\(name)-\(look)")
        }

        // Profile, then "App info": the first real screen.
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
        keep(app, "app-info-\(look)")

        let copy = app.descendants(matching: .any)["app-info.copy"].firstMatch
        copy.tap()
        XCTAssertTrue(app.buttons["Copied"].waitForExistence(timeout: 5), "Copying did not say it copied.")

        app.terminate()
    }

    private func keep(_ app: XCUIApplication, _ name: String) {
        let picture = XCTAttachment(screenshot: app.screenshot())
        picture.name = name
        picture.lifetime = .keepAlways
        add(picture)
    }
}
