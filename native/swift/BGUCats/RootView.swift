import SwiftUI

/// The first screen: decided by who is signed in. A launch is never a
/// blank screen: every state here says what it is.
struct RootView: View {
    let world: World
    @ObservedObject var session: Session

    var body: some View {
        Group {
            switch session.phase {
            case .starting:
                StartingView()
            case .signedOut(let note):
                SignInView(world: world, session: session, note: note)
            case .failed(let why):
                FailedView(world: world, session: session, why: why)
            case .signedIn(let me):
                TabsView(world: world, session: session, me: me)
            }
        }
        .task {
            await session.load()
            world.trail.mark("start: ready")
        }
        .preferredColorScheme(world.look)
    }
}

/// While the account is being read. A call gives up after twenty seconds,
/// so this never stays for ever.
struct StartingView: View {
    var body: some View {
        ProgressView("Loading…")
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Signed in, and the account could not be read: says why, and offers the
/// three things that can help.
struct FailedView: View {
    let world: World
    @ObservedObject var session: Session
    let why: String

    var body: some View {
        NavigationStack {
            ContentUnavailableView {
                Label("The app could not start", systemImage: "wifi.exclamationmark")
            } description: {
                Text(why)
            } actions: {
                Button("Try again") {
                    Task { await session.load() }
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("start.retry")
                NavigationLink("App info") {
                    AppInfoView(world: world)
                }
                Button("Sign out", role: .destructive) {
                    session.signOut()
                }
            }
        }
    }
}

/// The four tabs. The bar is the system's own, so its glass is iOS's and
/// follows the phone's settings (transparency, contrast, text size).
enum AppTab: String, CaseIterable {
    case cats, scan, home, profile
}

struct TabsView: View {
    let world: World
    @ObservedObject var session: Session
    let me: Me
    @State private var tab: AppTab = .home

    var body: some View {
        TabView(selection: $tab) {
            Tab("Cats", systemImage: "cat", value: AppTab.cats) {
                NotBuiltYet(title: "Cats", symbol: "cat")
            }
            Tab("Scan a cat", systemImage: "camera", value: AppTab.scan) {
                ScanView(world: world)
            }
            Tab("Home", systemImage: "house", value: AppTab.home) {
                FeedView(world: world)
            }
            Tab("Profile", systemImage: "person.crop.circle", value: AppTab.profile) {
                ProfileView(world: world, session: session, me: me)
            }
        }
        .onChange(of: tab) { _, opened in
            world.trail.mark("tab: \(opened.rawValue)")
        }
        // Photos left waiting by the last launch go on now, with no tap.
        .task {
            world.outbox.open()
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
    @ObservedObject var session: Session
    let me: Me

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        AvatarView(
                            person: Person(userId: me.userId, username: me.username, displayName: me.displayName, avatar: me.avatar),
                            photos: world.photos,
                            size: 56
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(me.displayName)
                                .font(.headline)
                            if let username = me.username {
                                Text("@\(username)")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("profile.me")
                    LabeledContent("Cats met", value: "\(me.catsMet)")
                    LabeledContent("Encounters", value: "\(me.encounters)")
                }
                Section {
                    NavigationLink {
                        AppInfoView(world: world)
                    } label: {
                        Label("App info", systemImage: "info.circle")
                    }
                    .accessibilityIdentifier("row.app-info")
                }
                Section {
                    Button("Sign out", role: .destructive) {
                        session.signOut()
                    }
                    .accessibilityIdentifier("profile.sign-out")
                }
            }
            .navigationTitle("Profile")
        }
    }
}
