import SwiftUI

/// Cats: every campus cat (`GET /cats`), two columns of covers, today's cat
/// of the day above them, a search field and the web app's ways to sort
/// (`web/social/gallery.js`). Fifty cats is one answer, so they are sorted
/// and searched on the phone, as the API's own note says. A cover opens
/// the cat's page on the tab's own stack, and coming back finds the
/// gallery as it was left: the search, the sort, the place in the list.
struct CatsView: View {
    let world: World
    let session: Session
    @StateObject private var model: CatsModel
    @State private var search = ""
    /// Nil until chosen: the first of `sorts`, as the web app opens.
    @State private var sort: CatSort?

    init(world: World, session: Session) {
        self.world = world
        self.session = session
        _model = StateObject(wrappedValue: CatsModel(world: world))
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Cats")
                .navigationDestination(for: CatRoute.self) { route in
                    CatView(world: world, session: session, catId: route.id)
                }
                .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search cats")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        sortMenu
                    }
                }
        }
        .task {
            await model.open()
        }
    }

    private var words: String {
        search.trimmingCharacters(in: .whitespaces)
    }

    private var chosenSort: CatSort {
        let offered = CatSort.offered(for: model.cats)
        if let sort, offered.contains(sort) {
            return sort
        }
        return offered[0]
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .loading:
            ProgressView("Loading…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let why):
            ContentUnavailableView {
                Label("The cats could not be loaded.", systemImage: "wifi.exclamationmark")
            } description: {
                Text(why)
            } actions: {
                Button("Try again") {
                    Task { await model.refresh() }
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("cats.retry")
            }
        case .loaded:
            let shown = CatSort.sorted(model.cats, by: chosenSort, search: words)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // The cat of the day while nothing is searched: a
                    // search is for one cat, and this is not it.
                    if words.isEmpty, let today = model.catOfTheDay {
                        CatOfTheDay(cat: today, photos: world.photos)
                    }
                    if !shown.isEmpty {
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)], spacing: 18) {
                            ForEach(shown) { cat in
                                NavigationLink(value: CatRoute(id: cat.id)) {
                                    CatTile(cat: cat, photos: world.photos)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("gallery.\(cat.id)")
                            }
                        }
                    }
                }
                .padding()
            }
            .overlay {
                if shown.isEmpty {
                    if words.isEmpty {
                        ContentUnavailableView("No cats yet.", systemImage: "cat")
                    } else {
                        ContentUnavailableView(
                            "No cat called “\(words)”.",
                            systemImage: "magnifyingglass"
                        )
                        .accessibilityIdentifier("cats.none")
                    }
                }
            }
            .refreshable {
                await model.refresh()
            }
        }
    }

    /// The system's menu, the sorts the web app offers, the chosen one
    /// checked.
    private var sortMenu: some View {
        Menu {
            Picker("Sort cats by", selection: Binding(get: { chosenSort }, set: { sort = $0 })) {
                ForEach(CatSort.offered(for: model.cats)) { option in
                    Text(option.words).tag(option)
                }
            }
        } label: {
            Label("Sort cats", systemImage: "arrow.up.arrow.down")
        }
        .accessibilityIdentifier("cats.sort")
    }
}

/// Where the tab's stack goes: a cat's page.
struct CatRoute: Hashable {
    let id: String
}

/// The web app's ways to sort the gallery, in its order and with its words
/// (`SORTS` in web/social/gallery.js, `gallery.sort.*` in en.json).
enum CatSort: String, CaseIterable, Identifiable {
    case gpa, seen, posts, newest, name

    var id: String { rawValue }

    var words: String {
        switch self {
        case .gpa: "Highest GPA"
        case .seen: "Recently seen"
        case .posts: "Most posts"
        case .newest: "Newest on campus"
        case .name: "Name A–Z"
        }
    }

    /// "Highest GPA" is offered, first, only when there are grades: the
    /// server sends none with the `gpa` flag off. The web app asks the
    /// flag; this app reads what the flag leaves in the answer.
    static func offered(for cats: [Cat]) -> [CatSort] {
        cats.contains { $0.gpa != nil } ? allCases : allCases.filter { $0 != .gpa }
    }

    /// The cats whose name holds the words, in this order. A tie goes to
    /// the cat seen last, as in the web app.
    static func sorted(_ cats: [Cat], by sort: CatSort, search: String) -> [Cat] {
        let found = search.isEmpty ? cats : cats.filter { ($0.name ?? "").localizedCaseInsensitiveContains(search) }
        func seen(_ a: Cat, _ b: Cat) -> Bool {
            (a.lastSeenAt ?? .distantPast) > (b.lastSeenAt ?? .distantPast)
        }
        return found.sorted { a, b in
            switch sort {
            case .gpa:
                let (x, y) = (a.gpa ?? 0, b.gpa ?? 0)
                return x != y ? x > y : seen(a, b)
            case .seen:
                return seen(a, b)
            case .posts:
                let (x, y) = (a.posts ?? 0, b.posts ?? 0)
                return x != y ? x > y : seen(a, b)
            case .newest:
                return (a.firstSeenAt ?? .distantPast) > (b.firstSeenAt ?? .distantPast)
            case .name:
                // A cat with no name comes after every named one.
                switch (a.name, b.name) {
                case let (x?, y?): return x.localizedCaseInsensitiveCompare(y) == .orderedAscending
                case (.some, nil): return true
                default: return false
                }
            }
        }
    }
}

@MainActor
final class CatsModel: ObservableObject {
    enum Phase {
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var cats: [Cat] = []
    @Published private(set) var catOfTheDay: Cat?
    @Published private(set) var phase: Phase = .loading

    private let world: World
    private var opened = false
    private var reading = false

    init(world: World) {
        self.world = world
    }

    /// The first read. Coming back to the tab reads nothing again: pulling
    /// down does.
    func open() async {
        guard !opened else { return }
        opened = true
        await refresh()
    }

    func refresh() async {
        guard !reading else { return }
        reading = true
        defer { reading = false }
        if cats.isEmpty {
            phase = .loading
        }
        do {
            let list = try await world.backend.catList()
            cats = list.cats
            catOfTheDay = list.cats.first { $0.id == list.catOfTheDay }
            phase = .loaded
            world.trail.mark("cats: \(list.cats.count) listed")
        } catch {
            // A sign-in that ended is the session's to say.
            if FeedModel.signInEnded(error) { return }
            // What is on screen stays if there is something.
            if cats.isEmpty {
                phase = .failed((error as? ApiError)?.message ?? "Try again.")
            }
        }
    }
}

/// Today's cat: its larger picture, its name and where it is usually. The
/// heading stands outside the link, which reads as one button.
private struct CatOfTheDay: View {
    let cat: Cat
    let photos: Photos

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Cat of the day")
                .font(.headline)
            NavigationLink(value: CatRoute(id: cat.id)) {
                VStack(alignment: .leading, spacing: 8) {
                    Color.clear
                        .aspectRatio(16 / 10, contentMode: .fit)
                        .overlay {
                            PhotoView(url: cat.coverMedium ?? cat.cover, photos: photos)
                        }
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(cat.shownName)
                            .font(.title3.weight(.semibold))
                        if let area = cat.area {
                            Text(area)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("cats.today")
        }
    }
}

/// One cat in the grid: its cover, its name and its area.
private struct CatTile: View {
    let cat: Cat
    let photos: Photos

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Color.clear
                .aspectRatio(1, contentMode: .fit)
                .overlay {
                    PhotoView(url: cat.cover, photos: photos)
                }
                .clipShape(RoundedRectangle(cornerRadius: 16))
            Text(cat.shownName)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
            if let area = cat.area {
                Text(area)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .contentShape(Rectangle())
    }
}
