import SwiftUI

/// The iPhone app, in Swift (docs/ROADMAP.md, 2g). This is the frame: four
/// tabs of system controls, and "App info". Screens follow one by one.
@main
struct BGUCatsApp: App {
    private let world = World.current()

    init() {
        world.trail.mark("start: launched")
    }

    var body: some Scene {
        WindowGroup {
            RootView(world: world)
        }
    }
}

/// Everything a screen reads from outside itself, so that a UI test can
/// hand the app a made-up one: a fixed clock and a trail kept in memory.
struct World {
    let trail: Trail
    let now: () -> Date
    let version: String

    /// The real one, or the stand-in when a UI test started the app.
    static func current(arguments: [String] = ProcessInfo.processInfo.arguments) -> World {
        if arguments.contains("-uiTesting") {
            return .standIn()
        }
        let info = Bundle.main.infoDictionary ?? [:]
        let version = "\(info["CFBundleShortVersionString"] ?? "?") (\(info["CFBundleVersion"] ?? "?"))"
        return World(trail: Trail(), now: Date.init, version: version)
    }

    /// What every UI test sees: the same lines at the same time, so two
    /// pictures of one screen are the same picture.
    static func standIn() -> World {
        let start = Date(timeIntervalSince1970: 1_795_000_000)
        var tick = 0.0
        let clock: () -> Date = {
            tick += 1.5
            return start.addingTimeInterval(tick)
        }
        return World(trail: Trail(store: MemoryStore(), now: clock), now: { start }, version: "0.2.0 (test)")
    }
}
