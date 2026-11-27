import SwiftUI

/// A cat's page, pushed on the Cats tab's stack (`GET /cats/{catId}`, the
/// web app's `web/social/cat.js`): its photos in a paged strip, its name
/// and what named it, its place and coat, the description, the numbers the
/// server sent, "You met" when the member has, and below them the cat's
/// posts (`GET /cats/{catId}/posts`) on the feed's own card, like and menu
/// and all. What the server leaves out is left out here.
struct CatView: View {
    let world: World
    let catId: String
    @State private var phase: Phase = .loading
    @StateObject private var posts: FeedModel

    enum Phase {
        case loading
        case loaded(CatDetail)
        case failed(String)
    }

    init(world: World, session: Session, catId: String) {
        self.world = world
        self.catId = catId
        _posts = StateObject(wrappedValue: FeedModel(world: world, session: session, source: .cat(catId)))
    }

    var body: some View {
        content
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .postActions(posts, world: world)
            .task {
                if case .loading = phase {
                    world.trail.mark("cats: opened a cat")
                    await load()
                }
            }
            .task {
                await posts.open()
            }
    }

    private var title: String {
        if case .loaded(let detail) = phase {
            return detail.cat.shownName
        }
        return ""
    }

    @ViewBuilder private var content: some View {
        switch phase {
        case .loading:
            ProgressView("Loading…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let why):
            ContentUnavailableView {
                Label("This cat could not be read", systemImage: "wifi.exclamationmark")
            } description: {
                Text(why)
            } actions: {
                Button("Try again") {
                    Task { await load() }
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("cat.retry")
            }
        case .loaded(let detail):
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    CatPhotos(detail: detail, photos: world.photos)
                    CatAbout(detail: detail, now: world.now())
                        .padding(.horizontal)
                    postsSection
                }
                .padding(.vertical)
            }
            .refreshable {
                await load()
                await posts.refresh()
            }
        }
    }

    /// The cat's posts, newest first, on the feed's card.
    @ViewBuilder private var postsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Recent posts")
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
                    Text("Nobody has posted this cat yet.")
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                        .accessibilityIdentifier("cat.no-posts")
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

    private func load() async {
        do {
            phase = .loaded(try await world.backend.cat(id: catId))
        } catch {
            // A sign-in that ended is the session's to say.
            if FeedModel.signInEnded(error) { return }
            let why = (error as? ApiError)?.message ?? "Try again."
            // A page on screen stays when a pull fails.
            if case .loaded = phase { return }
            phase = .failed(why)
        }
    }
}

/// The photos, square, one at a time; more than one are swiped, with the
/// system's page dots. None: nothing in their place.
private struct CatPhotos: View {
    let detail: CatDetail
    let photos: Photos

    var body: some View {
        if !detail.photos.isEmpty {
            Color.clear
                .aspectRatio(1, contentMode: .fit)
                .overlay {
                    if detail.photos.count == 1 {
                        PhotoView(url: detail.photos[0].medium ?? detail.photos[0].thumb, photos: photos)
                    } else {
                        TabView {
                            ForEach(detail.photos) { photo in
                                PhotoView(url: photo.medium ?? photo.thumb, photos: photos)
                            }
                        }
                        .tabViewStyle(.page)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .padding(.horizontal)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(count)
                .accessibilityIdentifier("cat.photos")
        }
    }

    private var count: String {
        detail.photos.count == 1 ? "1 photo" : "\(detail.photos.count) photos"
    }
}

/// The name, what named it, where it is usually, its coat, the
/// description, the numbers, and "You met". Each is shown only if the
/// server sent it.
private struct CatAbout: View {
    let detail: CatDetail
    let now: Date

    private var cat: Cat { detail.cat }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                Text(cat.shownName)
                    .font(.title.weight(.bold))
                    .accessibilityIdentifier("cat.name")
                if let named = cat.named {
                    Text(named)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("cat.named")
                }
            }

            if cat.area != nil || cat.coatName != nil {
                VStack(alignment: .leading, spacing: 6) {
                    if let area = cat.area {
                        Label("Usually near \(area)", systemImage: "mappin.and.ellipse")
                            .accessibilityIdentifier("cat.area")
                    }
                    if let coat = cat.coatName {
                        Label(coat, systemImage: "pawprint")
                            .accessibilityIdentifier("cat.coat")
                    }
                }
                .font(.subheadline)
            }

            if let bio = detail.bio {
                Text(bio)
                    .accessibilityIdentifier("cat.bio")
            }

            if !numbers.isEmpty {
                GroupBox {
                    VStack(spacing: 10) {
                        ForEach(numbers, id: \.label) { number in
                            LabeledContent(number.label, value: number.value)
                                .accessibilityIdentifier("cat.number.\(number.key)")
                        }
                    }
                }
            }

            if let met = detail.met {
                GroupBox("You met") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(CatAbout.met(met))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .accessibilityIdentifier("cat.met")
                        LabeledContent("Days", value: "\(met.days)")
                        if let first = met.firstDay {
                            LabeledContent("First", value: CatAbout.day(first))
                        }
                        if let last = met.lastDay {
                            LabeledContent("Last", value: CatAbout.day(last))
                        }
                    }
                }
            }
        }
    }

    private struct Number {
        let key: String
        let label: String
        let value: String
    }

    /// The numbers the server sent, in the web app's words and order, then
    /// when it was first seen, then the grade if there is one.
    private var numbers: [Number] {
        var shown: [Number] = []
        if let posts = cat.posts {
            shown.append(Number(key: "posts", label: posts == 1 ? "Post" : "Posts", value: "\(posts)"))
        }
        if let likes = cat.likes {
            shown.append(Number(key: "likes", label: likes == 1 ? "Like" : "Likes", value: "\(likes)"))
        }
        if let seen = cat.lastSeenAt {
            shown.append(Number(key: "last-seen", label: "Last seen", value: PostCard.age(of: seen, now: now)))
        }
        if let first = cat.firstSeenAt {
            shown.append(Number(key: "first-seen", label: "First seen", value: first.formatted(date: .abbreviated, time: .omitted)))
        }
        if let gpa = cat.gpa {
            shown.append(Number(key: "gpa", label: "GPA", value: String(format: "%.1f / 4", gpa)))
        }
        return shown
    }

    /// The web app's words (`cat.met`).
    static func met(_ met: Met) -> String {
        met.encounters == 1 ? "You met this cat once." : "You met this cat \(met.encounters) times."
    }

    /// An Israel day as the server wrote it, read at midnight UTC, so it
    /// is said in UTC: the same day on every phone.
    static func day(_ date: Date) -> String {
        var style = Date.FormatStyle(date: .abbreviated, time: .omitted)
        style.timeZone = TimeZone(identifier: "UTC") ?? .current
        return date.formatted(style)
    }
}
