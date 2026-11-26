import Foundation

/// Where the member is in Scan a cat after "Send": the encounter, its
/// photos in order, which cat they said it was (or the new cat they are
/// describing), and what they are writing.
/// Kept on the phone beside the upload queue (`Outbox.keepFlow`), so a
/// closed app opens on the same page. What was kept is checked before it
/// is used (`read`): a flow that is not whole is dropped, as the web app
/// drops one (`tests/web/test_member_flow_kept.py`).
struct ScanFlow: Codable, Equatable {
    enum Step: String, Codable {
        /// Sent; the cat not chosen yet. Leaving here makes no post.
        case sent
        case which
        /// "A cat that isn't here": the new-cat form.
        case new
        case post
        /// "Post" was tapped: the pick or the proposal, and the post, are
        /// in the queue.
        case posted
        /// "Just add" was tapped: the proposal is in the queue, no post.
        case added
    }

    /// A new cat as the member describes it (`POST /proposals`). Every
    /// answer is optional; each is one of the server's fixed choices
    /// (`Campus`).
    struct Proposal: Codable, Equatable {
        var nameIdea = ""
        var coat: String?
        var regionId: String?
        var traits: [String] = []

        /// Every answer is one the server takes.
        var whole: Bool {
            ScanFlow.length(nameIdea) <= ScanFlow.nameLimit
                && (coat.map { coat in Campus.coats.contains { $0.id == coat } } ?? true)
                && (regionId.map { region in region == Campus.elsewhere.id || Campus.places.contains { $0.id == region } } ?? true)
                && Set(traits).count == traits.count
                && traits.allSatisfy { trait in Campus.traits.contains { $0.id == trait } }
        }

        /// The name idea as it goes, and as the post page names the cat.
        var name: String? {
            let words = nameIdea.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            return words.isEmpty ? nil : words
        }
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
    /// "A cat that isn't here": the form's answers. Absent from a flow kept
    /// before this existed.
    var proposal: Proposal?
    /// Made once, at the first "Just add" or "Post" of a new cat, so a
    /// retry is the same proposal.
    var proposalId: String?
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
    /// `POST /proposals` takes a name idea of up to 24.
    static let nameLimit = 24

    /// The length the server checks: code points after NFKC
    /// (src/common/text.py), not what Swift calls characters. "❤️" is one
    /// character and two code points; counted as one, a description of
    /// emoji passed here and was refused for good there.
    static func length(_ text: String) -> Int {
        text.precomposedStringWithCompatibilityMapping.unicodeScalars.count
    }

    /// The longest start of `text` within the limit, cut between
    /// characters so no emoji or pointed letter is left half.
    static func cut(_ text: String, to limit: Int = textLimit) -> String {
        guard length(text) > limit else { return text }
        var kept = ""
        var used = 0
        for character in text {
            used += length(String(character))
            if used > limit { break }
            kept.append(character)
        }
        return kept
    }

    /// "Post" or "Just add" was tapped: what follows is in the queue, and
    /// nothing in the flow changes any more.
    var ended: Bool {
        step == .posted || step == .added
    }

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
            ScanFlow.length(text) <= ScanFlow.textLimit,
            !(unsure && catId != nil),
            proposal == nil || (catId == nil && !unsure && proposal?.whole == true),
            proposalId.map(ScanFlow.isUlid) ?? true
        else { return false }
        if let catId, catId.isEmpty {
            return false
        }
        let said = catId != nil || unsure || proposal != nil
        // A new cat's id is made before anything of it is queued.
        let proposed = proposal == nil || proposalId != nil
        switch step {
        case .sent, .which:
            return true
        case .new:
            return proposal != nil
        case .post:
            return said
        case .posted:
            return said && proposed && postId.map(ScanFlow.isUlid) == true
        case .added:
            return proposal != nil && proposed
        }
    }

    /// 26 characters of Crockford's base 32, as `Ulid.make` writes them.
    static func isUlid(_ text: String) -> Bool {
        text.count == 26 && text.allSatisfy { Ulid.alphabet.contains($0) }
    }

    /// What "Post" or "Just add" queues: the pick for a cat chosen (none
    /// for "Not sure", none for a new cat: with no model nothing was shown),
    /// the proposal for a new cat, and the post with every photo in order
    /// once it has an id ("Just add" makes none). Nil while an id that is
    /// needed has not been made.
    func writes() -> (pick: PickBody?, proposal: ProposalBody?, post: PostBody?)? {
        var proposed: ProposalBody?
        if let proposal {
            guard let proposalId else { return nil }
            proposed = ProposalBody(
                proposalId: proposalId,
                sessionId: encounterId,
                nameIdea: proposal.name,
                coat: proposal.coat,
                regionId: proposal.regionId,
                traits: proposal.traits
            )
        }
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let post = postId.map { postId in
            PostBody(
                postId: postId,
                sessionId: encounterId,
                photoIds: photos.map(\.id),
                catId: unsure ? nil : catId,
                proposalId: proposed?.proposalId,
                text: words.isEmpty ? nil : words,
                shareRegion: shareRegion
            )
        }
        let pick = unsure ? nil : catId.map { PickBody(catId: $0, photoCount: photos.count) }
        return (pick, proposed, post)
    }
}
