import XCTest

/// Not a test of the app: it wakes the simulator, and its result is not
/// counted. The job runs it by itself before the walk
/// (`.github/workflows/ios.yml`, "wake the simulator").
///
/// A simulator that has just started is busy for its first minutes, and
/// whatever runs first pays for it. On 2026-11-24 the first walk failed
/// three runs in a row with the app right, each time somewhere else: one
/// launch took 118 seconds, one question to the simulator took 29, and
/// once the simulator could not close the app. The second walk, on the
/// same simulator a few minutes later, passed every time.
///
/// So this opens the app, waits for its first screen and closes it, until
/// one such round is quick or four minutes have gone. It asserts nothing:
/// what it meets on the way (a launch or a close that fails) is the very
/// thing it is here to take, and `ScreensUITests` decides.
final class WarmUpUITests: XCTestCase {
    func testTheSimulatorIsAwake() {
        let started = Date()
        for round in 1...5 {
            let from = Date()
            let app = XCUIApplication()
            app.launchArguments = ["-uiTesting", "-signedOut"]
            app.launch()
            let up = app.descendants(matching: .any)["sign-in.google"].firstMatch.waitForExistence(timeout: 120)
            app.terminate()
            let took = Int(Date().timeIntervalSince(from))
            print("warm-up: round \(round) took \(took) s; the sign-in screen \(up ? "came up" : "did not come up")")
            if up && took < 20 { return }
            if Date().timeIntervalSince(started) > 240 { return }
        }
    }
}
