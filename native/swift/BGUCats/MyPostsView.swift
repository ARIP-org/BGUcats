import SwiftUI

/// My posts (`GET /me/posts`; the web app's `MyPosts` in
/// web/social/home.js, and its words): the member's posts, those others
/// cannot see included, each on the feed's own card with its state in
/// words when it is not public. Delete is in each card's menu, as in the
/// feed, through the same `FeedModel` and `postActions`. Read again each
/// time the page opens.
struct MyPostsView: View {
    let world: World
    @StateObject private var model: FeedModel

    init(world: World, session: Session) {
        self.world = world
        _model = StateObject(wrappedValue: FeedModel(world: world, session: session, source: .mine))
    }

    var body: some View {
        content
            .navigationTitle(ProfileWords.myPosts)
            .navigationBarTitleDisplayMode(.inline)
            .postActions(model, world: world)
            .task {
                await model.open()
            }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .loading:
            ProgressView("Loading…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("my-posts.loading")
        case .failed(let why):
            ContentUnavailableView {
                Label(MyPostsWords.failed, systemImage: "wifi.exclamationmark")
            } description: {
                Text(why)
            } actions: {
                Button("Try again") {
                    Task { await model.refresh() }
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("my-posts.retry")
            }
        case .loaded:
            if model.posts.isEmpty {
                ContentUnavailableView {
                    Label(ProfileWords.myPosts, systemImage: "camera")
                } description: {
                    Text(MyPostsWords.none)
                        .accessibilityIdentifier("my-posts.none")
                }
            } else {
                ScrollView {
                    LazyVStack(spacing: 28) {
                        ForEach(model.posts) { post in
                            PostCard(post: post, world: world, model: model)
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

/// The web app's words for My posts (web/i18n/en.json).
enum MyPostsWords {
    static let none = "You haven't posted yet. Scan a cat to make your first post."
    static let failed = "Your posts could not be loaded."
}
