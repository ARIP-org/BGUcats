import SwiftUI

/// Friends (`GET /friends`; the web app's `Friends` in
/// web/social/friends.js, and its words), opened from Profile: who found the
/// most cats this month or in all, as a podium of the first three (the
/// member among them), then every friend with a search over the list the
/// phone already holds. Each friend's menu removes them, blocks them or
/// reports them; a row or a place on the podium opens their page
/// (`PersonView`). The system's own `List`, segmented `Picker`, search
/// field, `Menu` and alerts.
struct FriendsView: View {
    let world: World
    let session: Session
    @StateObject private var model: FriendsModel
    @State private var period: FriendsPeriod = .month
    @State private var search = ""
    /// The person whose page is open.
    @State private var opened: Person?

    init(world: World, session: Session) {
        self.world = world
        self.session = session
        _model = StateObject(wrappedValue: FriendsModel(world: world))
    }

    var body: some View {
        List {
            Section {
                Picker(FriendsWords.period, selection: $period) {
                    Text(FriendsWords.month).tag(FriendsPeriod.month)
                    Text(FriendsWords.allTime).tag(FriendsPeriod.all)
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("friends.period")
            }
            if model.loaded {
                Section {
                    Podium(people: Array(model.people.prefix(3)), photos: world.photos) { person in
                        opened = person
                    }
                }
                friendsSection
            }
        }
        .overlay {
            switch model.phase {
            case .loading:
                ProgressView("Loading…")
                    .accessibilityIdentifier("friends.loading")
            case .failed(let why):
                ContentUnavailableView {
                    Label(FriendsWords.failed, systemImage: "wifi.exclamationmark")
                } description: {
                    Text(why)
                } actions: {
                    Button("Try again") {
                        Task { await model.load(period) }
                    }
                    .buttonStyle(.glassProminent)
                    .accessibilityIdentifier("friends.retry")
                }
            case .loaded:
                EmptyView()
            }
        }
        .navigationTitle(FriendsWords.title)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .always), prompt: FriendsWords.search)
        .navigationDestination(item: $opened) { person in
            PersonView(world: world, session: session, person: person)
        }
        .personDialogs(
            toRemove: $model.toRemove,
            toBlock: $model.toBlock,
            reporting: $model.reporting,
            note: $model.note,
            world: world,
            remove: { person in Task { await model.remove(person) } },
            block: { person in Task { await model.block(person) } }
        )
        .onChange(of: period) { _, now in
            Task { await model.load(now) }
        }
        // Removed or blocked from their page: they leave this list too.
        .onReceive(NotificationCenter.default.publisher(for: People.changed)) { note in
            if let change = People.read(note) {
                model.drop(change.userId)
            }
        }
        .refreshable {
            await model.load(period)
        }
        .task {
            await model.open()
        }
    }

    /// Every friend (the member is on the podium only), filtered by the
    /// search; the web app's words when there is nobody, or nobody matches.
    @ViewBuilder private var friendsSection: some View {
        let friends = model.people.filter { !$0.me }
        if friends.isEmpty {
            Section {
                Text(FriendsWords.empty)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("friends.empty")
            }
        } else {
            let listed = friends.filter { FriendsModel.matches($0.person, search) }
            Section {
                ForEach(listed) { friend in
                    row(friend)
                }
                if listed.isEmpty {
                    Text(FriendsWords.fill(FriendsWords.noMatch, ["search": search.trimmingCharacters(in: .whitespaces)]))
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("friends.none")
                }
            } header: {
                HStack {
                    Text(FriendsWords.all)
                    Spacer()
                    Text(FriendsWords.plural(FriendsWords.countOne, FriendsWords.countOther, friends.count))
                }
            }
        }
    }

    /// A friend: face, name, "@username · found 3 cats", opening their
    /// page; and their menu, Report last and red.
    private func row(_ friend: Friend) -> some View {
        let name = friend.person.shownName
        let found = FriendsWords.plural(FriendsWords.foundOne, FriendsWords.foundOther, friend.found)
        let under = friend.person.username.map { "@\($0) · \(found)" } ?? found
        return HStack(spacing: 12) {
            Button {
                opened = friend.person
            } label: {
                HStack(spacing: 12) {
                    AvatarView(person: friend.person, photos: world.photos, size: 46)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(name)
                            .font(.body.weight(.semibold))
                            .foregroundStyle(Color.primary)
                        Text(under)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .accessibilityLabel(friend.person.username.map { "\(name), @\($0), \(found)" } ?? "\(name), \(found)")
            .accessibilityIdentifier("friend.\(friend.id)")

            Menu {
                Button(FriendsWords.remove, systemImage: "person.badge.minus") {
                    model.toRemove = friend.person
                }
                Button(FriendsWords.block, systemImage: "hand.raised") {
                    model.toBlock = friend.person
                }
                Button(FriendsWords.report, systemImage: "flag", role: .destructive) {
                    model.reporting = friend.person
                }
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .accessibilityLabel(FriendsWords.fill(FriendsWords.optionsFor, ["name": name]))
            .accessibilityIdentifier("friend.menu.\(friend.id)")
        }
    }
}

/// The first three, the first in the middle with a crown, each with their
/// face and "N cats"; a tap opens their page. A place nobody holds is left
/// empty.
private struct Podium: View {
    let people: [Friend]
    let photos: Photos
    let open: (Person) -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            place(2)
            place(1)
            place(3)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }

    @ViewBuilder private func place(_ place: Int) -> some View {
        if people.indices.contains(place - 1) {
            let friend = people[place - 1]
            let name = FriendsWords.nameOf(friend)
            let cats = FriendsWords.plural(FriendsWords.catsOne, FriendsWords.catsOther, friend.found)
            Button {
                open(friend.person)
            } label: {
                VStack(spacing: 6) {
                    if place == 1 {
                        Image(systemName: "crown.fill")
                            .foregroundStyle(.yellow)
                    }
                    AvatarView(person: friend.person, photos: photos, size: place == 1 ? 56 : 48)
                    Text(name)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.primary)
                        .lineLimit(1)
                    Text(cats)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color.accentColor.opacity(place == 1 ? 0.35 : 0.2))
                        .frame(height: place == 1 ? 72 : place == 2 ? 52 : 38)
                        .overlay {
                            Text("\(place)")
                                .font(.title3.weight(.bold))
                                .foregroundStyle(Color.primary)
                        }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("\(place). \(name), \(cats)")
            .accessibilityIdentifier("podium.\(place)")
        } else {
            Color.clear
                .frame(maxWidth: .infinity, maxHeight: 1)
        }
    }
}

/// What the friends page reads and sends. A friend removed or blocked
/// leaves the list at once; a call that fails puts them back where they
/// were and says why.
@MainActor
final class FriendsModel: ObservableObject {
    enum Phase {
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var people: [Friend] = []
    @Published private(set) var phase: Phase = .loading
    /// Asked about in the system's confirmation, or reported in the sheet.
    @Published var toRemove: Person?
    @Published var toBlock: Person?
    @Published var reporting: Person?
    /// Something that failed, in words.
    @Published var note: String?

    private let world: World
    /// The period last asked for: an answer for another one is dropped.
    private var period: FriendsPeriod = .month
    private var opened = false

    init(world: World) {
        self.world = world
    }

    var loaded: Bool {
        if case .loaded = phase { return true }
        return false
    }

    /// The first read. Coming back from a person's page reads nothing again.
    func open() async {
        guard !opened else { return }
        opened = true
        await load(period)
    }

    func load(_ period: FriendsPeriod) async {
        self.period = period
        do {
            let answer = try await world.backend.friends(period: period)
            guard period == self.period else { return }
            people = answer
            phase = .loaded
            world.trail.mark("friends: \(answer.count) people (\(period.rawValue))")
        } catch {
            guard period == self.period else { return }
            if FeedModel.signInEnded(error) { return }
            let why = (error as? ApiError)?.message ?? "Try again."
            if loaded {
                // What is on screen stays; the failure is said over it.
                note = FriendsWords.failure(why)
            } else {
                phase = .failed(why)
            }
        }
    }

    /// Searched on the phone, by name or username (`matches` in the web app).
    static func matches(_ person: Person, _ search: String) -> Bool {
        let words = search.trimmingCharacters(in: .whitespaces).lowercased()
        return words.isEmpty || "\(person.displayName) \(person.username ?? "")".lowercased().contains(words)
    }

    /// Someone removed or blocked here or on their page.
    func drop(_ userId: String) {
        people.removeAll { $0.id == userId }
    }

    /// "Remove from friends", confirmed. Asks no terms: the API needs none.
    func remove(_ person: Person) async {
        toRemove = nil
        let (row, index) = takeOut(person)
        do {
            try await world.backend.removeFriend(userId: person.userId)
            world.trail.mark("friends: removed")
            People.post(person.userId, .unfriended)
        } catch {
            putBack(row, at: index)
            world.trail.mark("friends: remove failed (\((error as? ApiError)?.status ?? 0))")
            if FeedModel.signInEnded(error) { return }
            note = FriendsWords.failure((error as? ApiError)?.message ?? "Try again.")
        }
    }

    /// "Block", confirmed: they leave the list, and their posts the lists
    /// on screen. Asks no terms: the API needs none.
    func block(_ person: Person) async {
        toBlock = nil
        let (row, index) = takeOut(person)
        do {
            try await world.backend.block(userId: person.userId)
            world.trail.mark("block: sent")
            People.post(person.userId, .blocked)
        } catch {
            putBack(row, at: index)
            world.trail.mark("block: failed (\((error as? ApiError)?.status ?? 0))")
            if FeedModel.signInEnded(error) { return }
            note = FriendsWords.failure((error as? ApiError)?.message ?? "Try again.")
        }
    }

    private func takeOut(_ person: Person) -> (Friend?, Int) {
        guard let index = people.firstIndex(where: { $0.id == person.userId }) else { return (nil, 0) }
        let row: Friend? = people.remove(at: index)
        return (row, index)
    }

    /// Back where it was, unless it is there already (a read came between).
    private func putBack(_ row: Friend?, at index: Int) {
        guard let row, !people.contains(where: { $0.id == row.id }) else { return }
        people.insert(row, at: min(index, people.count))
    }
}

/// A friend removed or someone blocked, said to every screen that shows
/// them: the friends page drops them, and a block takes their posts off
/// the lists of posts on screen.
enum People {
    static let changed = Notification.Name("bgucats.people.changed")

    enum Kind: String {
        case unfriended, blocked
    }

    static func post(_ userId: String, _ kind: Kind) {
        NotificationCenter.default.post(name: changed, object: nil, userInfo: ["userId": userId, "kind": kind.rawValue])
    }

    static func read(_ note: Notification) -> (userId: String, kind: Kind)? {
        guard let userId = note.userInfo?["userId"] as? String,
              let kind = (note.userInfo?["kind"] as? String).flatMap(Kind.init(rawValue:))
        else { return nil }
        return (userId, kind)
    }
}

/// The system's confirmations before a friend is removed or someone
/// blocked, the report sheet with a person as its target, and a failure's
/// words: the friends page and a person's page ask the same way.
struct PersonDialogs: ViewModifier {
    @Binding var toRemove: Person?
    @Binding var toBlock: Person?
    @Binding var reporting: Person?
    @Binding var note: String?
    let world: World
    let remove: (Person) -> Void
    let block: (Person) -> Void

    func body(content: Content) -> some View {
        content
            .alert(
                FriendsWords.fill(FriendsWords.removeTitle, ["name": toRemove?.shownName ?? ""]),
                isPresented: shown($toRemove),
                presenting: toRemove
            ) { person in
                Button(FriendsWords.removeButton, role: .destructive) {
                    remove(person)
                }
                Button("Cancel", role: .cancel) {
                    world.trail.mark("friends: remove cancelled")
                }
            } message: { _ in
                Text(FriendsWords.removeBody)
            }
            .alert(
                FriendsWords.fill(FriendsWords.blockTitle, ["name": toBlock?.shownName ?? ""]),
                isPresented: shown($toBlock),
                presenting: toBlock
            ) { person in
                Button(FriendsWords.blockButton, role: .destructive) {
                    block(person)
                }
                Button("Cancel", role: .cancel) {
                    world.trail.mark("block: cancelled")
                }
            } message: { _ in
                Text(FriendsWords.blockBody)
            }
            .alert("That did not work", isPresented: noteShown) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(note ?? "")
            }
            .sheet(item: $reporting) { person in
                ReportView(person: person, world: world)
            }
    }

    private func shown(_ binding: Binding<Person?>) -> Binding<Bool> {
        Binding(get: { binding.wrappedValue != nil }, set: { up in
            if !up {
                binding.wrappedValue = nil
            }
        })
    }

    private var noteShown: Binding<Bool> {
        Binding(get: { note != nil }, set: { up in
            if !up {
                note = nil
            }
        })
    }
}

extension View {
    func personDialogs(
        toRemove: Binding<Person?>,
        toBlock: Binding<Person?>,
        reporting: Binding<Person?>,
        note: Binding<String?>,
        world: World,
        remove: @escaping (Person) -> Void,
        block: @escaping (Person) -> Void
    ) -> some View {
        modifier(PersonDialogs(
            toRemove: toRemove, toBlock: toBlock, reporting: reporting, note: note,
            world: world, remove: remove, block: block
        ))
    }
}

/// The web app's words for friends, a person's page and blocking
/// (web/i18n/en.json), as written there, `{name}` and `{count}` and all; a
/// Linux test holds them to it.
enum FriendsWords {
    static let title = "Friends"
    static let you = "You"
    static let period = "Period"
    static let month = "This month"
    static let allTime = "All time"
    static let catsOne = "{count} cat"
    static let catsOther = "{count} cats"
    static let foundOne = "found {count} cat"
    static let foundOther = "found {count} cats"
    static let search = "Search by name or username"
    static let all = "All friends"
    static let countOne = "{count} friend"
    static let countOther = "{count} friends"
    static let noMatch = "No friends match “{search}”."
    static let empty = "No friends here yet. Send your link to someone: whoever opens it becomes your friend."
    static let failed = "Your friends could not be loaded."
    static let optionsFor = "Options for {name}"
    static let remove = "Remove from friends"
    static let removeTitle = "Remove {name} from friends?"
    static let removeBody = "You will stop seeing roughly where they post, and they where you do. Either of you can send a link again."
    static let removeButton = "Remove"
    static let block = "Block"
    static let blockTitle = "Block {name}?"
    static let blockBody = "You will not see each other's posts or pages, and you will stop being friends. They are not told."
    static let blockButton = "Block"
    static let report = "Report"
    static let generic = "Something went wrong: {message}"
    static let personFoundOne = "{count} cat found"
    static let personFoundOther = "{count} cats found"
    static let friendsSince = "Friends since {date}"
    static let mutualOne = "{count} friend in common"
    static let mutualOther = "{count} friends in common"
    static let thisIsYou = "This is you"
    static let posts = "Posts"
    static let noPosts = "{name} has not posted yet."
    static let gone = "This person is not here any more."

    /// A template with its blanks filled.
    static func fill(_ template: String, _ values: [String: String]) -> String {
        values.reduce(template) { said, value in
            said.replacingOccurrences(of: "{\(value.key)}", with: value.value)
        }
    }

    /// The one or the other of a pair, with the count in it.
    static func plural(_ one: String, _ other: String, _ count: Int) -> String {
        fill(count == 1 ? one : other, ["count": "\(count)"])
    }

    /// A failure in the web app's words (`error.generic`).
    static func failure(_ message: String) -> String {
        fill(generic, ["message": message])
    }

    /// The member is "You" (`nameOf` in the web app).
    static func nameOf(_ friend: Friend) -> String {
        friend.me ? you : friend.person.shownName
    }
}
