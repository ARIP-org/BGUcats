import SwiftUI

/// The iPhone app, in Swift (docs/ROADMAP.md, 2g): what TestFlight gets.
/// Built so far: signing in, the feed, the profile's first rows and "App
/// info". The other tabs say they are not built yet.
@main
struct BGUCatsApp: App {
    private let world: World
    @StateObject private var session: Session

    init() {
        let world = World.current()
        self.world = world
        _session = StateObject(wrappedValue: Session(world: world))
        world.trail.mark("start: launched")
    }

    var body: some Scene {
        WindowGroup {
            RootView(world: world, session: session)
        }
    }
}

/// Everything a screen reads from outside itself, so that a UI test can
/// hand the app a made-up one: a fixed clock, a trail kept in memory, a
/// made-up member with made-up posts, and pictures that are drawn.
struct World {
    let trail: Trail
    let now: () -> Date
    let version: String
    /// Light or dark, when a UI test asks for one; nil follows the phone.
    var look: ColorScheme?
    let gate: Gate
    let backend: Backend
    let photos: Photos
    /// The upload queue, and where the phone is when a photo is taken.
    let outbox: Outbox
    let places: Places
    /// The Scan screen hands out drawn photos instead of opening the camera
    /// or the gallery (a UI test: the simulator has neither).
    let drawn: Bool

    /// The real one, or the stand-in when a UI test started the app.
    @MainActor
    static func current(arguments: [String] = ProcessInfo.processInfo.arguments) -> World {
        if arguments.contains("-uiTesting") {
            // "-signedOut": the test wants the sign-in screen.
            // "-signInEnds": the server refuses the token at the first like.
            // "-termsRequired": the member has not accepted the terms.
            // "-termsChanged": the terms changed after the account was read.
            // "-uploadFailsOnce": the second photo's upload times out once.
            // "-offline": no upload reaches the server.
            // "-keepQueue": the upload queue left by the last run is kept,
            // as a phone keeps it between launches; otherwise it is emptied.
            var world = World.standIn(
                signedIn: !arguments.contains("-signedOut"),
                ends: arguments.contains("-signInEnds"),
                termsRequired: arguments.contains("-termsRequired"),
                termsChanged: arguments.contains("-termsChanged"),
                failsOnce: arguments.contains("-uploadFailsOnce"),
                offline: arguments.contains("-offline"),
                keepQueue: arguments.contains("-keepQueue")
            )
            // "-look dark": the test names the look it is about to
            // picture. Asking the simulator to change its appearance did
            // nothing on the first run: every "dark" picture was light.
            if let flag = arguments.firstIndex(of: "-look"), arguments.indices.contains(flag + 1) {
                world.look = arguments[flag + 1] == "dark" ? .dark : .light
            }
            return world
        }
        let info = Bundle.main.infoDictionary ?? [:]
        let version = "\(info["CFBundleShortVersionString"] ?? "?") (\(info["CFBundleVersion"] ?? "?"))"
        let trail = Trail()
        let auth = Auth(vault: KeychainVault(), trail: trail)
        let backend = LiveBackend(auth: auth, trail: trail)
        return World(
            trail: trail,
            now: Date.init,
            version: version,
            look: nil,
            gate: auth,
            backend: backend,
            photos: NetPhotos(),
            outbox: Outbox(folder: Outbox.home, backend: backend, trail: trail),
            places: DevicePlaces(),
            drawn: false
        )
    }

    /// What every UI test sees: the same lines at the same time, so two
    /// pictures of one screen are the same picture. No network at all.
    @MainActor
    static func standIn(
        signedIn: Bool = true,
        ends: Bool = false,
        termsRequired: Bool = false,
        termsChanged: Bool = false,
        failsOnce: Bool = false,
        offline: Bool = false,
        keepQueue: Bool = false
    ) -> World {
        let start = Date(timeIntervalSince1970: 1_795_000_000)
        var tick = 0.0
        let clock: () -> Date = {
            tick += 1.5
            return start.addingTimeInterval(tick)
        }
        let gate = StandInGate(signedIn: signedIn)
        let trail = Trail(store: MemoryStore(), now: clock)
        let backend = StandInBackend(
            start: start,
            gate: gate,
            ends: ends,
            termsRequired: termsRequired,
            termsChanged: termsChanged,
            failsOnce: failsOnce,
            offline: offline
        )
        // The queue's files go to the app's temporary folder, emptied at
        // every launch unless the test is checking what a second launch
        // does with what the first one left.
        let queue = FileManager.default.temporaryDirectory.appendingPathComponent("ui-testing-outbox", isDirectory: true)
        if !keepQueue {
            try? FileManager.default.removeItem(at: queue)
        }
        return World(
            trail: trail,
            now: { start },
            version: "0.2.0 (test)",
            look: nil,
            gate: gate,
            backend: backend,
            photos: DrawnPhotos(),
            // A retry waits long enough for its picture to be taken.
            outbox: Outbox(folder: queue, backend: backend, trail: trail, waits: [12]),
            places: StandInPlaces(),
            drawn: true
        )
    }
}
