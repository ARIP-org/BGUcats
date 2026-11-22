import SwiftUI

/// The four tabs. The bar is the system's own, so its glass is iOS's and
/// follows the phone's settings (transparency, contrast, text size).
enum AppTab: String, CaseIterable {
    case cats, scan, home, profile
}

struct RootView: View {
    let world: World
    @State private var tab: AppTab = .home

    init(world: World) {
        self.world = world
    }

    var body: some View {
        TabView(selection: $tab) {
            Tab("Cats", systemImage: "cat", value: AppTab.cats) {
                NotBuiltYet(title: "Cats", symbol: "cat")
            }
            Tab("Scan a cat", systemImage: "camera", value: AppTab.scan) {
                NotBuiltYet(title: "Scan a cat", symbol: "camera")
            }
            Tab("Home", systemImage: "house", value: AppTab.home) {
                NotBuiltYet(title: "Home", symbol: "house")
            }
            Tab("Profile", systemImage: "person.crop.circle", value: AppTab.profile) {
                ProfileView(world: world)
            }
        }
        .onChange(of: tab) { _, opened in
            world.trail.mark("tab: \(opened.rawValue)")
        }
        .task {
            world.trail.mark("start: ready")
        }
    }
}

/// A tab whose screen is not built: it says so, in the system's own words
/// for an empty place.
struct NotBuiltYet: View {
    let title: LocalizedStringKey
    let symbol: String

    var body: some View {
        NavigationStack {
            ContentUnavailableView(
                "Not built yet",
                systemImage: symbol,
                description: Text("This screen is being rewritten for iPhone. Until it is here, the app on the home screen has it.")
            )
            .navigationTitle(title)
        }
    }
}

struct ProfileView: View {
    let world: World

    var body: some View {
        NavigationStack {
            List {
                NavigationLink {
                    AppInfoView(world: world)
                } label: {
                    Label("App info", systemImage: "info.circle")
                }
                .accessibilityIdentifier("row.app-info")
            }
            .navigationTitle("Profile")
        }
    }
}
