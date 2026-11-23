import SwiftUI

/// Home: the feed. Posts, newest first, a page at a time.
struct FeedView: View {
    let world: World
    @StateObject private var model: FeedModel

    init(world: World) {
        self.world = world
        _model = StateObject(wrappedValue: FeedModel(world: world))
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Home")
                .alert("That did not work", isPresented: noteShown) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text(model.note ?? "")
                }
        }
        .task {
            await model.open()
        }
    }

    private var noteShown: Binding<Bool> {
        Binding(get: { model.note != nil }, set: { shown in
            if !shown {
                model.note = nil
            }
        })
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
                            PostCard(post: post, world: world) {
                                Task { await model.toggleLike(post) }
                            }
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

@MainActor
final class FeedModel: ObservableObject {
    enum Phase {
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var posts: [Post] = []
    @Published private(set) var phase: Phase = .loading
    @Published private(set) var hasMore = false
    /// Something the person did that failed, in words for them.
    @Published var note: String?

    private let world: World
    private var cursor: String?
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
        do {
            let page = try await world.backend.feed(cursor: nil)
            posts = page.posts
            cursor = page.cursor
            hasMore = page.cursor != nil
            phase = .loaded
            world.trail.mark("feed: \(page.posts.count) posts")
        } catch {
            let why = (error as? ApiError)?.message ?? "Try again."
            if posts.isEmpty {
                phase = .failed(why)
            } else {
                // What is on screen stays; the pull says it failed.
                note = why
            }
        }
    }

    func more() async {
        guard !reading, let from = cursor else { return }
        reading = true
        defer { reading = false }
        do {
            let page = try await world.backend.feed(cursor: from)
            let known = Set(posts.map(\.id))
            posts += page.posts.filter { !known.contains($0.id) }
            cursor = page.cursor
            hasMore = page.cursor != nil
            world.trail.mark("feed: \(page.posts.count) more")
        } catch {
            // The spinner at the end goes; pulling down reads again.
            hasMore = false
        }
    }

    /// Counts at once, then asks the server; a refusal puts it back and
    /// says why.
    func toggleLike(_ post: Post) async {
        guard let index = posts.firstIndex(where: { $0.id == post.id }) else { return }
        let before = posts[index]
        let on = !before.liked
        posts[index].liked = on
        posts[index].likes = max(0, before.likes + (on ? 1 : -1))
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
            note = (error as? ApiError)?.message ?? "Try again."
            world.trail.mark("feed: a like failed")
        }
    }
}

/// One post: who, the photos, the like, which cat, the words.
struct PostCard: View {
    let post: Post
    let world: World
    let like: () -> Void

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
                .accessibilityLabel("Like")
                .accessibilityValue(post.liked ? "liked" : "not liked")

                if let cat = post.catName {
                    Label(cat, systemImage: "cat")
                        .font(.subheadline.weight(.medium))
                }
                Spacer()
                if post.state == "pending" {
                    Label("Being checked", systemImage: "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal)

            if !post.text.isEmpty {
                Text(post.text)
                    .padding(.horizontal)
            }
        }
        .accessibilityIdentifier("post.\(post.id)")
    }

    /// "@name · 2 hr. ago", with whichever of the two there is.
    private var under: String {
        var parts: [String] = []
        if let username = post.author.username {
            parts.append("@\(username)")
        }
        if let at = post.createdAt {
            let ago = RelativeDateTimeFormatter()
            ago.unitsStyle = .abbreviated
            parts.append(ago.localizedString(for: at, relativeTo: world.now()))
        }
        return parts.joined(separator: " · ")
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
