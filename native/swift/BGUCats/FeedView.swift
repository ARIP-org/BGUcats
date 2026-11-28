import SwiftUI

/// Home: the feed. Posts, newest first, a page at a time.
struct FeedView: View {
    let world: World
    @StateObject private var model: FeedModel
    /// A post made in Scan a cat reaches the server: the feed reads itself
    /// again, so the member finds it first when they come Home.
    @ObservedObject private var outbox: Outbox

    init(world: World, session: Session) {
        self.world = world
        _model = StateObject(wrappedValue: FeedModel(world: world, session: session))
        _outbox = ObservedObject(wrappedValue: world.outbox)
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Home")
                .postActions(model, world: world)
        }
        .task {
            await model.open()
        }
        // While Home is open, and when it is opened again: a tab out of
        // sight may not hear the change.
        .onChange(of: outbox.postsSent) { _, sent in
            Task { await model.catchUp(sent) }
        }
        .onAppear {
            Task { await model.catchUp(outbox.postsSent) }
        }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .loading:
            ProgressView("Loading…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let why):
            ContentUnavailableView {
                Label("The feed could not be read", systemImage: "wifi.exclamationmark")
            } description: {
                Text(why)
            } actions: {
                Button("Try again") {
                    Task { await model.refresh() }
                }
                .buttonStyle(.glassProminent)
            }
        case .loaded:
            if model.posts.isEmpty {
                ContentUnavailableView(
                    "No posts yet",
                    systemImage: "cat",
                    description: Text("When someone posts a cat they met, it shows here.")
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 28) {
                        ForEach(model.posts) { post in
                            PostCard(post: post, world: world, model: model)
                        }
                        if model.hasMore {
                            ProgressView()
                                .padding()
                                .task {
                                    await model.more()
                                }
                        }
                    }
                    .padding(.vertical)
                }
                .refreshable {
                    await model.refresh()
                }
            }
        }
    }
}

/// What a post's card can ask for, wherever its cards are drawn (Home, a
/// cat's page): the confirmation before a delete, the report sheet, and
/// the words when something the person did failed.
struct PostActions: ViewModifier {
    @ObservedObject var model: FeedModel
    let world: World

    func body(content: Content) -> some View {
        content
            .alert("That did not work", isPresented: noteShown) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.note ?? "")
            }
            // The system's confirmation before a post goes for everyone.
            .alert("Delete this post?", isPresented: deleteAsked, presenting: model.toDelete) { post in
                Button("Delete", role: .destructive) {
                    Task { await model.delete(post) }
                }
                .accessibilityIdentifier("post.delete.confirm")
                Button("Cancel", role: .cancel) {}
            } message: { _ in
                Text("It disappears from the feed for everyone. The photos stay with the cat's records.")
            }
            .sheet(item: $model.reporting) { post in
                ReportView(post: post, world: world)
            }
            // Someone blocked, from a friend's menu or their page: their
            // posts leave the list already on screen (`keptApart` in the
            // web app's feed).
            .onReceive(NotificationCenter.default.publisher(for: People.changed)) { note in
                if let change = People.read(note), change.kind == .blocked {
                    model.keepApart(change.userId)
                }
            }
    }

    private var noteShown: Binding<Bool> {
        Binding(get: { model.note != nil }, set: { shown in
            if !shown {
                model.note = nil
            }
        })
    }

    private var deleteAsked: Binding<Bool> {
        Binding(get: { model.toDelete != nil }, set: { shown in
            if !shown {
                model.toDelete = nil
            }
        })
    }
}

extension View {
    func postActions(_ model: FeedModel, world: World) -> some View {
        modifier(PostActions(model: model, world: world))
    }
}

/// A list of posts read a page at a time, with what a card can do to
/// them: Home's feed, or one cat's posts on its page.
@MainActor
final class FeedModel: ObservableObject {
    enum Phase {
        case loading
        case loaded
        case failed(String)
    }

    /// Which posts: the feed's, one cat's (`GET /cats/{catId}/posts`), the
    /// member's own (`GET /me/posts`, with each one's state), or one
    /// person's (`GET /users/{userId}/posts`).
    enum Source {
        case feed
        case cat(String)
        case mine
        case person(String)
    }

    @Published private(set) var posts: [Post] = []
    @Published private(set) var phase: Phase = .loading
    @Published private(set) var hasMore = false
    /// Something the person did that failed, in words for them.
    @Published var note: String?
    /// The member's own post they asked to delete, while the confirmation is up.
    @Published var toDelete: Post?
    /// Someone else's post being reported, while its sheet is up.
    @Published var reporting: Post?

    private let world: World
    /// Whose terms come first (`Session.termsFirst`).
    private let session: Session
    private let source: Source
    private var cursor: String?
    private var opened = false
    private var reading = false
    /// The outbox's count of posts sent when the feed was last caught up.
    private var postsRead = 0

    init(world: World, session: Session, source: Source = .feed) {
        self.world = world
        self.session = session
        self.source = source
    }

    /// What the trail calls this list: "feed" or "cat", never which cat.
    private var kind: String {
        switch source {
        case .feed: "feed"
        case .cat: "cat"
        case .mine: "my posts"
        case .person: "person"
        }
    }

    private func read(_ cursor: String?) async throws -> FeedPage {
        switch source {
        case .feed:
            try await world.backend.feed(cursor: cursor)
        case .cat(let id):
            try await world.backend.catPosts(id: id, cursor: cursor)
        case .mine:
            try await world.backend.myPosts()
        case .person(let id):
            try await world.backend.personPosts(userId: id, cursor: cursor)
        }
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
        do {
            let page = try await read(nil)
            posts = page.posts
            cursor = page.cursor
            hasMore = page.cursor != nil
            phase = .loaded
            world.trail.mark("\(kind): \(page.posts.count) posts")
        } catch {
            // A sign-in that ended is the session's to say: the sign-in
            // screen is on its way up.
            if FeedModel.signInEnded(error) { return }
            let why = (error as? ApiError)?.message ?? "Try again."
            if posts.isEmpty {
                phase = .failed(why)
            } else {
                // What is on screen stays; the pull says it failed.
                note = why
            }
        }
    }

    /// Reads the feed again if a post was made since it was last read.
    func catchUp(_ postsSent: Int) async {
        // A read under way may have begun before the post: the next
        // change or the next look at Home catches up.
        guard postsSent != postsRead, !reading else { return }
        postsRead = postsSent
        await refresh()
    }

    func more() async {
        guard !reading, let from = cursor else { return }
        reading = true
        defer { reading = false }
        do {
            let page = try await read(from)
            let known = Set(posts.map(\.id))
            posts += page.posts.filter { !known.contains($0.id) }
            cursor = page.cursor
            hasMore = page.cursor != nil
            world.trail.mark("\(kind): \(page.posts.count) more")
        } catch {
            // The spinner at the end goes; pulling down reads again.
            hasMore = false
        }
    }

    /// Counts at once, then asks the server; a refusal puts it back and
    /// says why. A like is a write: the terms come first, and a "no" sends
    /// nothing and counts nothing. Taking a like back writes nothing for
    /// others, and the API asks no terms for it.
    func toggleLike(_ post: Post, termsChanged: Bool = false) async {
        guard let index = posts.firstIndex(where: { $0.id == post.id }) else { return }
        let before = posts[index]
        let on = !before.liked
        if on || termsChanged {
            do {
                guard try await session.termsFirst(changed: termsChanged) else { return }
            } catch {
                if FeedModel.signInEnded(error) { return }
                note = (error as? ApiError)?.message ?? "Try again."
                return
            }
        }
        // The dialog may have been up a while: the post as it is now.
        guard let at = posts.firstIndex(where: { $0.id == post.id }), posts[at].liked == before.liked else { return }
        posts[at].liked = on
        posts[at].likes = max(0, before.likes + (on ? 1 : -1))
        do {
            let count = try await world.backend.like(postId: post.id, on: on)
            if let now = posts.firstIndex(where: { $0.id == post.id }) {
                posts[now].likes = count
            }
        } catch {
            if let now = posts.firstIndex(where: { $0.id == post.id }) {
                posts[now].liked = before.liked
                posts[now].likes = before.likes
            }
            world.trail.mark("\(kind): a like failed")
            if FeedModel.signInEnded(error) { return }
            if (error as? ApiError)?.code == "terms_required" && !termsChanged {
                // The terms changed since the account was read: ask once
                // more instead of showing the server's word.
                await toggleLike(before, termsChanged: true)
                return
            }
            note = (error as? ApiError)?.message ?? "Try again."
        }
    }

    /// Leaves the feed at once, then asks the server; a refusal puts the
    /// card back where it was and says why.
    func delete(_ post: Post) async {
        toDelete = nil
        guard let index = posts.firstIndex(where: { $0.id == post.id }) else { return }
        let card = posts.remove(at: index)
        do {
            try await world.backend.deletePost(postId: post.id)
            world.trail.mark("post: deleted")
        } catch {
            if !posts.contains(where: { $0.id == card.id }) {
                posts.insert(card, at: min(index, posts.count))
            }
            world.trail.mark("post: delete failed (\((error as? ApiError)?.status ?? 0))")
            if FeedModel.signInEnded(error) { return }
            note = (error as? ApiError)?.message ?? "Try again."
        }
    }

    /// A person blocked: their posts leave this list at once. The server
    /// leaves them out of every list read after.
    func keepApart(_ userId: String) {
        posts.removeAll { $0.author.userId == userId }
    }

    /// The sign-in is over: the server refused the token, or the account
    /// is being deleted (`gone`, 403). The session puts the sign-in screen
    /// up and says which; a screen says nothing of its own over it.
    static func signInEnded(_ error: Error) -> Bool {
        guard let refusal = error as? ApiError else { return false }
        return refusal.status == 401 || Session.isGone(refusal)
    }
}

/// One post: who, the photos, the like, which cat, the words; and its
/// menu: Delete on the member's own, Report on anyone else's.
struct PostCard: View {
    let post: Post
    let world: World
    let like: () -> Void
    let delete: () -> Void
    let report: () -> Void

    /// A card whose like, delete and report go to the list it is in
    /// (`FeedModel`), with `postActions` on a view around it.
    init(post: Post, world: World, model: FeedModel) {
        self.post = post
        self.world = world
        like = { Task { await model.toggleLike(post) } }
        delete = { model.toDelete = post }
        report = { model.reporting = post }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                AvatarView(person: post.author, photos: world.photos)
                VStack(alignment: .leading, spacing: 1) {
                    Text(post.author.displayName)
                        .font(.subheadline.weight(.semibold))
                    Text(under)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                menu
            }
            .padding(.horizontal)

            pictures

            HStack(spacing: 12) {
                Button(action: like) {
                    Label("\(post.likes)", systemImage: post.liked ? "heart.fill" : "heart")
                }
                .buttonStyle(.glass)
                .tint(post.liked ? Color.red : nil)
                .accessibilityIdentifier("like.\(post.id)")
                // The count is in the label, so a test (and VoiceOver) can read it.
                .accessibilityLabel("Like, \(post.likes)")
                .accessibilityValue(post.liked ? "liked" : "not liked")

                if let cat = post.catName {
                    Label(cat, systemImage: "cat")
                        .font(.subheadline.weight(.medium))
                }
                Spacer()
                // Its author's alone: why others do not see it (yet).
                if let words = post.stateWords {
                    Label(words, systemImage: post.state == "hidden" ? "eye.slash" : "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        // One element, read as its words: a Label's
                        // identifier otherwise lands on the symbol too,
                        // which answers "Clock" (2026-11-27).
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(words)
                        .accessibilityIdentifier("post.state.\(post.id)")
                }
            }
            .padding(.horizontal)

            if !post.text.isEmpty {
                Text(post.text)
                    .padding(.horizontal)
            }
        }
    }

    /// The system's menu on an ellipsis.
    private var menu: some View {
        Menu {
            if post.mine {
                Button("Delete post", systemImage: "trash", role: .destructive, action: delete)
                    .accessibilityIdentifier("post.delete")
            } else {
                Button("Report", systemImage: "flag", action: report)
                    .accessibilityIdentifier("post.report")
            }
        } label: {
            Image(systemName: "ellipsis")
                .frame(width: 32, height: 32)
                .contentShape(Rectangle())
        }
        .foregroundStyle(.secondary)
        .accessibilityLabel("More")
        .accessibilityIdentifier("menu.\(post.id)")
    }

    /// "@name · 2 hr. ago", with whichever of the two there is.
    private var under: String {
        var parts: [String] = []
        if let username = post.author.username {
            parts.append("@\(username)")
        }
        if let at = post.createdAt {
            parts.append(Self.age(of: at, now: world.now()))
        }
        return parts.joined(separator: " · ")
    }

    /// How old a post is, as the web app says it (`ago` in
    /// web/social/i18n.js): under a minute either way is "Just now". A
    /// post made a moment ago carries the server's clock, which can be a
    /// second ahead of the phone's, and read "in 0s" (2026-11-26).
    static func age(of at: Date, now: Date) -> String {
        if abs(at.timeIntervalSince(now)) < 60 {
            return "Just now"
        }
        let ago = RelativeDateTimeFormatter()
        ago.unitsStyle = .abbreviated
        return ago.localizedString(for: at, relativeTo: now)
    }

    /// The photos, square, one at a time; more than one can be swiped.
    @ViewBuilder private var pictures: some View {
        if post.photos.isEmpty {
            EmptyView()
        } else {
            Color.clear
                .aspectRatio(1, contentMode: .fit)
                .overlay {
                    if post.photos.count == 1 {
                        PhotoView(url: post.photos[0].medium ?? post.photos[0].thumb, photos: world.photos)
                    } else {
                        TabView {
                            ForEach(post.photos) { photo in
                                PhotoView(url: photo.medium ?? photo.thumb, photos: world.photos)
                            }
                        }
                        .tabViewStyle(.page)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .padding(.horizontal)
        }
    }
}
