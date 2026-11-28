import SwiftUI
import UIKit

/// A person's page (`GET /users/{userId}`; the web app's `PersonPage` in
/// web/social/friends.js, and its words), opened from the friends page:
/// their face, name and username; chips for the cats they found, since
/// when the two are friends, the friends in common and "This is you"; and
/// their posts (`GET /users/{userId}/posts`) on the feed's own card. The
/// same menu as a friend's row is in the bar, Remove only while they are
/// friends; blocked, their page goes and the friends page is back. A person
/// who is not here any more says so.
struct PersonView: View {
    let world: World
    /// As the friends page had them: the bar's title until the page is read.
    let person: Person
    @StateObject private var model: PersonModel
    @StateObject private var posts: FeedModel
    @Environment(\.dismiss) private var dismiss

    init(world: World, session: Session, person: Person) {
        self.world = world
        self.person = person
        _model = StateObject(wrappedValue: PersonModel(world: world, userId: person.userId))
        _posts = StateObject(wrappedValue: FeedModel(world: world, session: session, source: .person(person.userId)))
    }

    var body: some View {
        content
            .navigationTitle(model.detail?.person.shownName ?? person.shownName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if let detail = model.detail, !detail.me {
                    ToolbarItem(placement: .topBarTrailing) {
                        menu(detail)
                    }
                }
            }
            .postActions(posts, world: world)
            .personDialogs(
                toRemove: $model.toRemove,
                toBlock: $model.toBlock,
                reporting: $model.reporting,
                note: $model.note,
                world: world,
                remove: { person in Task { await model.remove(person) } },
                block: { person in Task { await model.block(person) } }
            )
            // Blocked: their page is gone, back to where one came from.
            .onChange(of: model.left) { _, left in
                if left {
                    dismiss()
                }
            }
            .task {
                if model.detail == nil {
                    world.trail.mark("person: opened")
                    await model.load()
                }
            }
            .task {
                await posts.open()
            }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .loading:
            ProgressView("Loading…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .gone:
            ContentUnavailableView {
                Label(person.shownName, systemImage: "person.crop.circle.badge.xmark")
            } description: {
                Text(FriendsWords.gone)
                    .accessibilityIdentifier("person.gone")
            }
        case .failed(let why):
            ContentUnavailableView {
                Label(person.shownName, systemImage: "wifi.exclamationmark")
            } description: {
                Text(FriendsWords.failure(why))
            } actions: {
                Button("Try again") {
                    Task {
                        await model.load()
                        await posts.refresh()
                    }
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("person.retry")
            }
        case .loaded(let detail):
            ScrollView {
                VStack(spacing: 22) {
                    header(detail)
                    postsSection(detail)
                }
                .padding(.vertical)
            }
            .refreshable {
                await model.load()
                await posts.refresh()
            }
        }
    }

    /// The face, the names, and the chips the server's answer earns.
    private func header(_ detail: PersonDetail) -> some View {
        VStack(spacing: 12) {
            AvatarView(person: detail.person, photos: world.photos, size: 96)
            VStack(spacing: 2) {
                Text(detail.person.shownName)
                    .font(.title2.weight(.bold))
                    .accessibilityIdentifier("person.name")
                if let username = detail.person.username {
                    Text("@\(username)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("person.username")
                }
            }
            ChipsLayout(spacing: 8) {
                chip(FriendsWords.plural(FriendsWords.personFoundOne, FriendsWords.personFoundOther, detail.found), id: "found", accent: true)
                if detail.friend, let since = detail.friendSince {
                    chip(FriendsWords.fill(FriendsWords.friendsSince, ["date": PersonView.monthYear(since)]), id: "since")
                }
                if let mutual = detail.mutual, mutual > 0 {
                    chip(FriendsWords.plural(FriendsWords.mutualOne, FriendsWords.mutualOther, mutual), id: "mutual")
                }
                if detail.me {
                    chip(FriendsWords.thisIsYou, id: "you")
                }
            }
        }
        .padding(.horizontal)
        .frame(maxWidth: .infinity)
    }

    private func chip(_ words: String, id: String, accent: Bool = false) -> some View {
        Text(words)
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(accent ? Color.accentColor.opacity(0.18) : Color(uiColor: .tertiarySystemFill), in: Capsule())
            .accessibilityIdentifier("person.chip.\(id)")
    }

    /// Their posts, newest first, on the feed's card.
    @ViewBuilder private func postsSection(_ detail: PersonDetail) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(FriendsWords.posts)
                .font(.headline)
                .padding(.horizontal)
            switch posts.phase {
            case .loading:
                ProgressView()
                    .frame(maxWidth: .infinity)
            case .failed(let why):
                VStack(alignment: .leading, spacing: 8) {
                    Text(why)
                        .foregroundStyle(.secondary)
                    Button("Try again") {
                        Task { await posts.refresh() }
                    }
                    .buttonStyle(.glass)
                }
                .padding(.horizontal)
            case .loaded:
                if posts.posts.isEmpty {
                    Text(FriendsWords.fill(FriendsWords.noPosts, ["name": detail.person.shownName]))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                        .accessibilityIdentifier("person.no-posts")
                }
                LazyVStack(spacing: 28) {
                    ForEach(posts.posts) { post in
                        PostCard(post: post, world: world, model: posts)
                    }
                    if posts.hasMore {
                        ProgressView()
                            .padding()
                            .task {
                                await posts.more()
                            }
                    }
                }
            }
        }
    }

    /// The friend's menu, in the bar: Remove while they are friends,
    /// Block, and Report last and red.
    private func menu(_ detail: PersonDetail) -> some View {
        Menu {
            if detail.friend {
                Button(FriendsWords.remove, systemImage: "person.badge.minus") {
                    model.toRemove = detail.person
                }
            }
            Button(FriendsWords.block, systemImage: "hand.raised") {
                model.toBlock = detail.person
            }
            Button(FriendsWords.report, systemImage: "flag", role: .destructive) {
                model.reporting = detail.person
            }
        } label: {
            Image(systemName: "ellipsis")
        }
        .accessibilityLabel(FriendsWords.fill(FriendsWords.optionsFor, ["name": detail.person.shownName]))
        .accessibilityIdentifier("person.menu")
    }

    /// "Mar 2026", as the web app's `monthYear`.
    static func monthYear(_ date: Date) -> String {
        date.formatted(.dateTime.month(.abbreviated).year())
    }
}

/// What a person's page reads and sends.
@MainActor
final class PersonModel: ObservableObject {
    enum Phase {
        case loading
        case loaded(PersonDetail)
        /// Nobody, an account going away, or someone a block keeps apart.
        case gone
        case failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    @Published var toRemove: Person?
    @Published var toBlock: Person?
    @Published var reporting: Person?
    @Published var note: String?
    /// Blocked from here: the page goes.
    @Published private(set) var left = false

    private let world: World
    private let userId: String

    init(world: World, userId: String) {
        self.world = world
        self.userId = userId
    }

    var detail: PersonDetail? {
        if case .loaded(let detail) = phase { return detail }
        return nil
    }

    func load() async {
        do {
            phase = .loaded(try await world.backend.person(userId: userId))
        } catch {
            if FeedModel.signInEnded(error) { return }
            let refusal = error as? ApiError
            if refusal?.code == "gone" {
                world.trail.mark("person: gone")
                phase = .gone
                return
            }
            // A page on screen stays when a pull fails.
            if detail != nil { return }
            phase = .failed(refusal?.message ?? "Try again.")
        }
    }

    /// "Remove from friends", confirmed: the page stays, no longer a friend's.
    func remove(_ person: Person) async {
        toRemove = nil
        do {
            try await world.backend.removeFriend(userId: person.userId)
            world.trail.mark("friends: removed")
            if var now = detail {
                now.friend = false
                now.friendSince = nil
                phase = .loaded(now)
            }
            People.post(person.userId, .unfriended)
        } catch {
            world.trail.mark("friends: remove failed (\((error as? ApiError)?.status ?? 0))")
            if FeedModel.signInEnded(error) { return }
            note = FriendsWords.failure((error as? ApiError)?.message ?? "Try again.")
        }
    }

    /// "Block", confirmed: their posts leave the lists on screen and the
    /// page goes.
    func block(_ person: Person) async {
        toBlock = nil
        do {
            try await world.backend.block(userId: person.userId)
            world.trail.mark("block: sent")
            People.post(person.userId, .blocked)
            left = true
        } catch {
            world.trail.mark("block: failed (\((error as? ApiError)?.status ?? 0))")
            if FeedModel.signInEnded(error) { return }
            note = FriendsWords.failure((error as? ApiError)?.message ?? "Try again.")
        }
    }
}

/// Chips in rows, each row centred, a new row when the next chip does not
/// fit.
struct ChipsLayout: Layout {
    var spacing: CGFloat = 8

    private struct Row {
        var items: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let lines = rows(width: proposal.width ?? .infinity, subviews: subviews)
        let height = lines.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(lines.count - 1, 0))
        let width = lines.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in rows(width: bounds.width, subviews: subviews) {
            var x = bounds.minX + max(0, bounds.width - row.width) / 2
            for index in row.items {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(
                    at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                    proposal: ProposedViewSize(size)
                )
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private func rows(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            if !row.items.isEmpty && row.width + spacing + size.width > width {
                rows.append(row)
                row = Row()
            }
            row.width = row.items.isEmpty ? size.width : row.width + spacing + size.width
            row.items.append(index)
            row.height = max(row.height, size.height)
        }
        if !row.items.isEmpty {
            rows.append(row)
        }
        return rows
    }
}
