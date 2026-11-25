import Foundation

/// Where the member is in Scan a cat after "Send": the encounter, its
/// photos in order, which cat they said it was, and what they are writing.
/// Kept on the phone beside the upload queue (`Outbox.keepFlow`), so a
/// closed app opens on the same page. What was kept is checked before it
/// is used (`read`): a flow that is not whole is dropped, as the web app
/// drops one (`tests/web/test_member_flow_kept.py`).
struct ScanFlow: Codable, Equatable {
    enum Step: String, Codable {
        /// Sent; the cat not chosen yet. Leaving here makes no post.
        case sent
        case which
        case post
        /// "Post" was tapped: the pick and the post are in the queue.
        case posted
    }

    struct Shot: Codable, Equatable {
        let id: String
        let gallery: Bool
    }

    let encounterId: String
    /// Every photo of the encounter, in the order they were taken.
    let photos: [Shot]
    var step: Step
    /// The cat chosen, and its name for the page (on this phone only).
    var catId: String?
    var catName: String?
    /// "Not sure": no cat, and no pick.
    var unsure: Bool
    var text: String
    /// "Add location": on unless turned off, as in the web app.
    var shareRegion: Bool
    /// Made once, at the first "Post", so a retry is the same post.
    var postId: String?

    init(encounterId: String, photos: [Shot]) {
        self.encounterId = encounterId
        self.photos = photos
        step = .sent
        unsure = false
        text = ""
        shareRegion = true
    }

    /// `POST /posts` takes up to 280 characters and up to 50 photos.
    static let textLimit = 280
    static let photoLimit = 50

    /// What the last launch kept, if it is whole; nil if it is not.
    static func read(_ data: Data) -> ScanFlow? {
        guard let flow = try? JSONDecoder().decode(ScanFlow.self, from: data), flow.whole else { return nil }
        return flow
    }

    /// Every part is there and agrees with the others.
    var whole: Bool {
        let ids = photos.map(\.id)
        guard
            ScanFlow.isUlid(encounterId),
            !ids.isEmpty, ids.count <= ScanFlow.photoLimit,
            Set(ids).count == ids.count,
            ids.allSatisfy(ScanFlow.isUlid),
            text.count <= ScanFlow.textLimit,
            !(unsure && catId != nil)
        else { return false }
        if let catId, catId.isEmpty {
            return false
        }
        switch step {
        case .sent, .which:
            return true
        case .post:
            return catId != nil || unsure
        case .posted:
            return (catId != nil || unsure) && postId.map(ScanFlow.isUlid) == true
        }
    }

    /// 26 characters of Crockford's base 32, as `Ulid.make` writes them.
    static func isUlid(_ text: String) -> Bool {
        text.count == 26 && text.allSatisfy { Ulid.alphabet.contains($0) }
    }

    /// What "Post" queues: the pick for a cat chosen (none for "Not sure"),
    /// and the post with every photo in order.
    func writes() -> (pick: PickBody?, post: PostBody)? {
        guard let postId else { return nil }
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let post = PostBody(
            postId: postId,
            sessionId: encounterId,
            photoIds: photos.map(\.id),
            catId: unsure ? nil : catId,
            text: words.isEmpty ? nil : words,
            shareRegion: shareRegion
        )
        let pick = unsure ? nil : catId.map { PickBody(catId: $0, photoCount: photos.count) }
        return (pick, post)
    }
}
