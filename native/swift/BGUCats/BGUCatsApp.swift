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

    /// The real one, or the stand-in when a UI test started the app.
    static func current(arguments: [String] = ProcessInfo.processInfo.arguments) -> World {
        if arguments.contains("-uiTesting") {
            // "-signedOut": the test wants the sign-in screen.
            // "-signInEnds": the server refuses the token at the first like.
            // "-termsRequired": the member has not accepted the terms.
            // "-termsChanged": the terms changed after the account was read.
            var world = World.standIn(
                signedIn: !arguments.contains("-signedOut"),
                ends: arguments.contains("-signInEnds"),
                termsRequired: arguments.contains("-termsRequired"),
                termsChanged: arguments.contains("-termsChanged")
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
        return World(
            trail: trail,
            now: Date.init,
            version: version,
            look: nil,
            gate: auth,
            backend: LiveBackend(auth: auth, trail: trail),
            photos: NetPhotos()
        )
    }

    /// What every UI test sees: the same lines at the same time, so two
    /// pictures of one screen are the same picture. No network at all.
    static func standIn(signedIn: Bool = true, ends: Bool = false, termsRequired: Bool = false, termsChanged: Bool = false) -> World {
        let start = Date(timeIntervalSince1970: 1_795_000_000)
        var tick = 0.0
        let clock: () -> Date = {
            tick += 1.5
            return start.addingTimeInterval(tick)
        }
        let gate = StandInGate(signedIn: signedIn)
        return World(
            trail: Trail(store: MemoryStore(), now: clock),
            now: { start },
            version: "0.2.0 (test)",
            look: nil,
            gate: gate,
            backend: StandInBackend(start: start, gate: gate, ends: ends, termsRequired: termsRequired, termsChanged: termsChanged),
            photos: DrawnPhotos()
        )
    }
}
