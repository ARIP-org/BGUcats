import SwiftUI
import UIKit

/// The upload queue: the web app's (web/outbox.js), for this app. What is
/// sent is written to the phone first (each photo's file, once, and a small
/// index beside them) and uploaded from there, so a dead spot on campus or a
/// closed app never loses a photo: the queue goes on at the next launch.
/// Nothing leaves the phone's storage until the server has confirmed it.
///
/// Every id is a ULID made here (`Ulid.swift`), so a retry after a lost
/// answer lands on the same records. The write order is the web app's: the encounter (with its
/// first photo, never empty), then for each photo its record as `pending`,
/// its bytes, and the confirmation. A photo never goes before its
/// encounter, and one photo's failure never holds up the others.
///
/// What follows the photos rides here too (rows 6, 8 and 9 of "The capture
/// flow" in docs/app-plan/04-api.md): the member's pick or their new cat's
/// proposal, then the post. Each waits until every photo of its encounter
/// is confirmed, goes once, in that order, and is kept in the index until
/// the server has it. `not_ready` is "try again shortly"; `already_posted`
/// is the post already there, `already_proposed` the proposal.
///
/// Beside the queue, the Scan screen's flow (`ScanFlow`): which encounter
/// it is about and how far the member got, kept so a closed app comes back
/// to the same page.
@MainActor
final class Outbox: ObservableObject {
    /// One photo as the screen shows it.
    enum State: Equatable {
        case waiting
        /// Its bytes are going: 0 to 1.
        case sending(Double)
        /// It failed and will be tried again; in words, why.
        case retrying(String)
        /// Refused for good; in words, why. "Try again" is a person's call.
        case failed(String)
        case sent
    }

    struct Shown: Identifiable {
        let id: String
        let gallery: Bool
        var thumb: UIImage?
    }

    /// What is kept in the index. No name, no picture: ids, places, times.
    struct Encounter: Codable {
        let id: String
        let place: Fix?
        var created: Bool
        /// What follows its photos, once "Post" was tapped. Absent from an
        /// index written before this existed: nothing follows.
        var after: After? = nil
    }

    /// The pick or the proposal, and the post, of one encounter, and which
    /// have gone.
    struct After: Codable, Equatable {
        var pick: PickBody?
        var pickSent = false
        /// Optional, both: an index kept before they existed has neither,
        /// and must still be read (a field it lacks would drop it whole).
        var proposal: ProposalBody?
        var proposalDone: Bool?
        var post: PostBody?
        var postSent = false
        /// The post, or with no post the proposal, refused for good, in
        /// words: it is not tried again.
        var postFailed: String?

        /// Something here is still to send.
        var pending: Bool {
            (pick != nil && !pickSent)
                || (proposal != nil && proposalDone != true)
                || (post != nil && !postSent && postFailed == nil)
        }

        /// Kept in the index: something is still to send, or a post was
        /// refused for good and its flow, which shows why, is not over. The
        /// refusal lives here only, so forgetting it would turn "Posted"
        /// after a launch into a post that was never made.
        var kept: Bool {
            pending || postFailed != nil
        }
    }

    /// A post as the screen shows it; with no post, a new cat's proposal.
    enum PostState: Equatable {
        /// Kept on the phone; it goes once the photos have.
        case waiting
        case sent
        case failed(String)
    }

    struct Item: Codable {
        let id: String
        let encounterId: String
        let gallery: Bool
        let capturedAt: Date?
        let place: Fix?
        var failed: String?
    }

    struct Index: Codable {
        var encounters: [Encounter] = []
        var items: [Item] = []
    }

    /// The photos of the last "Send", in order, with each one's state.
    @Published private(set) var batch: [Shown] = []
    @Published private(set) var states: [String: State] = [:]
    /// Each post "Post" queued (or proposal "Just add" queued), by its
    /// encounter.
    @Published private(set) var posts: [String: PostState] = [:]
    /// How many posts reached the server since the app opened: the feed
    /// reads itself again when it changes.
    @Published private(set) var postsSent = 0
    /// The Scan screen's flow, kept beside the queue; nil when none is open.
    @Published private(set) var flow: ScanFlow?
    /// The flow's small pictures, by photo id.
    @Published private(set) var flowThumbs: [String: UIImage] = [:]

    /// Photos in flight at once, as in the web app: each is three round
    /// trips, and on a phone's link waiting is most of the time.
    static let parallel = 3

    private let folder: URL
    private let backend: Backend
    private let trail: Trail
    /// Waits between passes that left something to try again, then the last.
    private let waits: [Double]
    private var index = Index()
    private var opened = false
    private var running = false
    private var again = false
    private var failures = 0
    private var sleeper: Task<Void, Never>?

    init(folder: URL, backend: Backend, trail: Trail, waits: [Double] = [2, 5, 15, 60]) {
        self.folder = folder
        self.backend = backend
        self.trail = trail
        self.waits = waits
    }

    /// Where the real app keeps its queue: its own storage, not the cache,
    /// which iOS may empty.
    static var home: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("outbox", isDirectory: true)
    }

    // ------------------------------------------------------------ the screen

    var sentCount: Int {
        batch.filter { states[$0.id] == .sent }.count
    }

    var failedCount: Int {
        batch.filter { if case .failed = states[$0.id] { return true } else { return false } }.count
    }

    /// Something of the batch is still on its way.
    var busy: Bool {
        batch.contains { shown in
            switch states[shown.id] {
            case .sent, .failed: return false
            default: return true
            }
        }
    }

    /// Opens the queue kept on the phone and sends what waits in it. The
    /// app's start, once signed in: no tap needed.
    func open() {
        guard !opened else {
            kick()
            return
        }
        opened = true
        if let data = try? Data(contentsOf: indexFile), let kept = try? JSONDecoder().decode(Index.self, from: data) {
            index = kept
        }
        // A record whose file is not there cannot be sent; a file with no
        // record was written by a "Send" that never finished writing.
        let files = Set((try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? [])
        index.items.removeAll { !files.contains(Outbox.fileName($0.id)) }
        let known = Set(index.items.map { Outbox.fileName($0.id) })
        for name in files where name.hasSuffix(".jpg") && !known.contains(name) {
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(name))
        }
        let kept = index.items
        index.encounters.removeAll { encounter in
            !kept.contains { $0.encounterId == encounter.id } && !(encounter.after?.kept ?? false)
        }
        save()
        for encounter in index.encounters where encounter.after?.post != nil || encounter.after?.proposal != nil {
            if let failed = encounter.after?.postFailed {
                posts[encounter.id] = .failed(failed)
            } else if encounter.after?.pending == true {
                posts[encounter.id] = .waiting
            }
        }
        openFlow()
        // A refusal is kept for its flow only: with that flow gone, so is it.
        dropRefused(keeping: flow?.encounterId)
        guard !index.items.isEmpty else {
            kick()
            return
        }

        batch = index.items.map { Shown(id: $0.id, gallery: $0.gallery, thumb: nil) }
        for item in index.items {
            states[item.id] = item.failed.map { .failed($0) } ?? .waiting
        }
        trail.mark("upload: \(index.items.count) waiting from before")
        // The small pictures, read away from the screen's thread.
        for item in index.items {
            let file = self.file(item.id)
            Task.detached(priority: .utility) {
                let small = UIImage(contentsOfFile: file.path).map(Shrink.thumb)
                await MainActor.run { self.setThumb(item.id, small) }
            }
        }
        kick()
    }

    /// "Send": writes the photos to the phone, then the index, then sends.
    /// `lateFix`: where the phone is now, for an encounter whose camera
    /// photos were all taken before the first fix.
    @discardableResult
    func send(_ photos: [Chosen], lateFix: Fix?) async throws -> String? {
        guard !photos.isEmpty else { return nil }
        let folder = self.folder
        try await Task.detached(priority: .userInitiated) {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            for photo in photos {
                // Written once and never again: only read from here on.
                try photo.jpeg.write(to: folder.appendingPathComponent(Outbox.fileName(photo.id)), options: .atomic)
            }
        }.value

        // The encounter is placed by its first camera photo that has a
        // place, never by a photo from the gallery.
        let camera = photos.filter { !$0.gallery }
        let place = camera.first(where: { $0.place != nil })?.place ?? (camera.isEmpty ? nil : lateFix)
        let encounter = Encounter(id: Ulid.make(), place: place, created: false)
        index.encounters.append(encounter)
        index.items += photos.map {
            Item(id: $0.id, encounterId: encounter.id, gallery: $0.gallery, capturedAt: $0.capturedAt, place: $0.gallery ? nil : $0.place, failed: nil)
        }
        save()
        batch = photos.map { Shown(id: $0.id, gallery: $0.gallery, thumb: $0.thumb) }
        for photo in photos {
            states[photo.id] = .waiting
        }
        trail.mark("upload: \(photos.count) photos queued")
        // The flow names only photos the queue already holds.
        startFlow(encounterId: encounter.id, photos: photos)
        kick()
        return encounter.id
    }

    /// "Try again" on photos refused for good.
    func retryFailed() {
        for at in index.items.indices where index.items[at].failed != nil {
            index.items[at].failed = nil
            states[index.items[at].id] = .waiting
        }
        save()
        kick()
    }

    /// "Scan another cat": the batch and the flow leave the screen, and
    /// photos refused for good leave the phone, and any post waiting for
    /// them goes without them (or not at all, if none is left).
    func clear() {
        let dropped = Set(index.items.filter { $0.failed != nil }.map(\.id))
        for photoId in dropped {
            forget(photoId)
        }
        for at in index.encounters.indices {
            guard var post = index.encounters[at].after?.post, !dropped.isDisjoint(with: post.photoIds) else { continue }
            post.photoIds.removeAll { dropped.contains($0) }
            let encounterId = index.encounters[at].id
            if post.photoIds.isEmpty {
                index.encounters[at].after?.post = nil
                posts[encounterId] = nil
            } else {
                index.encounters[at].after?.post = post
            }
        }
        save()
        batch = []
        states = [:]
        endFlow()
    }

    /// "Post" or "Just add": the pick (nil for "Not sure" and a new cat),
    /// the proposal (a new cat's) and the post (nil for "Just add"), queued
    /// behind the encounter's photos. Its photos may all be on the server
    /// already, and the encounter forgotten here: it comes back, as created.
    func finish(encounterId: String, pick: PickBody?, proposal: ProposalBody? = nil, post: PostBody?) {
        let after = After(pick: pick, proposal: proposal, post: post)
        if let at = index.encounters.firstIndex(where: { $0.id == encounterId }) {
            index.encounters[at].after = after
        } else {
            index.encounters.append(Encounter(id: encounterId, place: nil, created: true, after: after))
        }
        posts[encounterId] = post == nil && proposal == nil ? nil : PostState.waiting
        save()
        let what: [String?] = [pick == nil ? "no pick" : "pick", proposal == nil ? nil : "a proposal", post == nil ? "no post" : "a post"]
        trail.mark("upload: \(what.compactMap { $0 }.joined(separator: ", ")) queued")
        kick()
    }

    // ------------------------------------------------------------ the sending

    func kick() {
        if running {
            again = true
            sleeper?.cancel()
            return
        }
        running = true
        Task { await drain() }
    }

    private func drain() async {
        while true {
            again = false
            let stuck = await pass()
            if again {
                continue
            }
            guard stuck else { break }
            failures += 1
            let wait = waits[min(failures, waits.count) - 1]
            let sleeper = Task<Void, Never> {
                try? await Task.sleep(for: .seconds(wait))
            }
            self.sleeper = sleeper
            await sleeper.value
            self.sleeper = nil
        }
        failures = 0
        running = false
    }

    /// One pass over the queue: the encounters first, then the photos of
    /// those that exist, three at a time. Answers whether something is left
    /// to try again.
    private func pass() async -> Bool {
        var stuck = false
        for encounter in index.encounters where !encounter.created {
            let items = index.items.filter { $0.encounterId == encounter.id && $0.failed == nil }
            guard !items.isEmpty else { continue }
            do {
                let status = try await backend.createEncounter(id: encounter.id, place: encounter.place)
                trail.mark("upload: encounter \(status)")
                if let at = index.encounters.firstIndex(where: { $0.id == encounter.id }) {
                    index.encounters[at].created = true
                }
                save()
            } catch {
                let outcome = Outbox.judge(error, step: "encounter")
                trail.mark(outcome.line)
                for item in items {
                    if outcome.again {
                        states[item.id] = .retrying(outcome.words)
                    } else {
                        refuse(item.id, outcome.words)
                    }
                }
                stuck = stuck || outcome.again
            }
        }

        let ready = Set(index.encounters.filter(\.created).map(\.id))
        let items = index.items.filter { ready.contains($0.encounterId) && $0.failed == nil }
        let later = await withTaskGroup(of: Bool.self, returning: Bool.self) { group in
            var queue = items[...]
            for _ in 0..<Outbox.parallel {
                if let item = queue.popFirst() {
                    group.addTask { await self.sendOne(item) }
                }
            }
            var later = false
            while let again = await group.next() {
                later = later || again
                if let item = queue.popFirst() {
                    group.addTask { await self.sendOne(item) }
                }
            }
            return later
        }
        let behind = await sendAfter()
        let left = index.items
        index.encounters.removeAll { encounter in
            encounter.created && !left.contains { $0.encounterId == encounter.id } && !(encounter.after?.kept ?? false)
        }
        save()
        return stuck || later || behind
    }

    /// The picks, proposals and posts whose photos are all confirmed: the
    /// pick or the proposal first, then the post, each once. Answers
    /// whether one must be tried again.
    private func sendAfter() async -> Bool {
        var again = false
        let waiting = Set(index.items.map(\.encounterId))
        for encounter in index.encounters where encounter.created && !waiting.contains(encounter.id) {
            guard let after = encounter.after, after.pending else { continue }
            if let pick = after.pick, !after.pickSent {
                do {
                    let status = try await backend.pick(encounterId: encounter.id, pick)
                    trail.mark("upload: pick \(status)")
                } catch {
                    let outcome = Outbox.judge(error, step: "pick")
                    trail.mark(outcome.line)
                    if outcome.again {
                        // The post waits for its pick: in order.
                        again = true
                        continue
                    }
                    // Refused (the cat merged away meanwhile): the post
                    // matters more than the answer, which is dropped.
                }
                changeAfter(encounter.id, from: after) { $0.pickSent = true }
            }
            if let proposal = after.proposal, after.proposalDone != true {
                do {
                    let status = try await backend.propose(proposal)
                    trail.mark("upload: proposal \(status)")
                } catch let failure as ApiError where failure.code == "already_proposed" {
                    // The encounter has its new cat on the server already
                    // (a retry whose first answer was lost): sent.
                    trail.mark("upload: proposal \(failure.status), already there")
                } catch {
                    let outcome = Outbox.judge(error, step: "proposal")
                    trail.mark(outcome.line)
                    if outcome.again {
                        // The post waits for its proposal: in order.
                        again = true
                        continue
                    }
                    // Refused for good: the post that names it cannot go
                    // either, and the screen says why.
                    changeAfter(encounter.id, from: after) {
                        $0.proposalDone = true
                        $0.postFailed = outcome.words
                    }
                    posts[encounter.id] = .failed(outcome.words)
                    continue
                }
                changeAfter(encounter.id, from: after) { $0.proposalDone = true }
                if after.post == nil {
                    // "Just add": the proposal was all there was to send.
                    posts[encounter.id] = .sent
                }
            }
            guard let post = after.post, !after.postSent, after.postFailed == nil else { continue }
            do {
                let status = try await backend.post(post)
                trail.mark("upload: post \(status)")
                postWent(encounter.id, post)
            } catch let failure as ApiError where failure.code == "already_posted" {
                // Another post of this encounter is on the server (a resent
                // postId is answered with its own post, not this). The
                // encounter is in the feed, which is what "Post" was for.
                trail.mark("upload: post \(failure.status), already there")
                postWent(encounter.id, post)
            } catch let failure as ApiError where failure.code == "not_ready" || failure.status == 425 {
                // A photo is still being processed: not an error to show.
                trail.mark("upload: post \(failure.status), not ready yet")
                again = true
            } catch {
                let outcome = Outbox.judge(error, step: "post")
                trail.mark(outcome.line)
                if outcome.again {
                    again = true
                } else {
                    changeAfter(encounter.id, from: nil) { $0.postFailed = outcome.words }
                    posts[encounter.id] = .failed(outcome.words)
                }
            }
        }
        return again
    }

    /// Changes what follows an encounter's photos, unless "Post" replaced
    /// it while a request was on its way (`from`: what was read; nil: any).
    private func changeAfter(_ encounterId: String, from: After?, _ change: (inout After) -> Void) {
        guard let at = index.encounters.firstIndex(where: { $0.id == encounterId }), var after = index.encounters[at].after else { return }
        if let from, from.pick != after.pick || from.proposal != after.proposal || from.post != after.post {
            return
        }
        change(&after)
        index.encounters[at].after = after
        save()
    }

    private func postWent(_ encounterId: String, _ post: PostBody) {
        guard let at = index.encounters.firstIndex(where: { $0.id == encounterId }), index.encounters[at].after?.post == post else { return }
        index.encounters[at].after?.postSent = true
        save()
        posts[encounterId] = .sent
        postsSent += 1
    }

    /// One photo: its record, its bytes, the confirmation. Answers whether
    /// it must be tried again.
    private func sendOne(_ item: Item) async -> Bool {
        states[item.id] = .sending(0)
        var step = "media"
        do {
            let started = try await backend.startPhoto(PhotoStart(
                encounterId: item.encounterId,
                photoId: item.id,
                capturedAt: item.capturedAt,
                gallery: item.gallery,
                place: item.place
            ))
            trail.mark("upload: media \(started.status)")
            if let target = started.target {
                step = "storage"
                let id = item.id
                let status = try await backend.upload(file(item.id), to: target) { [weak self] value in
                    Task { @MainActor in self?.progressed(id, value) }
                }
                trail.mark("upload: storage \(status)")
            }
            step = "complete"
            let status = try await backend.complete(photoId: item.id)
            trail.mark("upload: complete \(status)")
            forget(item.id)
            states[item.id] = .sent
            return false
        } catch {
            let outcome = Outbox.judge(error, step: step)
            trail.mark(outcome.line)
            if outcome.again {
                states[item.id] = .retrying(outcome.words)
                return true
            }
            refuse(item.id, outcome.words)
            return false
        }
    }

    /// What a failure means: try again or not, the words for the screen,
    /// and the trail's line (kinds and numbers, never an id).
    struct Outcome {
        let again: Bool
        let words: String
        let line: String
    }

    nonisolated static func judge(_ error: Error, step: String) -> Outcome {
        guard let failure = error as? ApiError else {
            return Outcome(again: true, words: "Something went wrong. Trying again.", line: "upload: retry, \(step) error")
        }
        switch failure.status {
        case 0:
            let kind = failure.code ?? "not reached"
            let words = kind == "timed out"
                ? "The upload took too long. Trying again."
                : "The server could not be reached. Trying again when it can."
            return Outcome(again: true, words: words, line: "upload: retry, \(kind)")
        case 401:
            return Outcome(again: true, words: "Your sign-in ended. It goes on once you sign in again.", line: "upload: retry, \(step) 401")
        case 409 where step == "complete":
            // Storage has not shown the file to the server yet.
            return Outcome(again: true, words: "Storage has not confirmed it yet. Trying again.", line: "upload: retry, \(step) 409")
        case 429 where step == "proposal":
            // Ten new cats a day: trying again within the day only fails.
            return Outcome(again: false, words: failure.message, line: "upload: failed, \(step) 429")
        case 400, 403, 404, 409, 413:
            return Outcome(again: false, words: failure.message, line: "upload: failed, \(step) \(failure.status)")
        case 400..<500 where step == "storage":
            return Outcome(again: false, words: failure.message, line: "upload: failed, \(step) \(failure.status)")
        default:
            return Outcome(again: true, words: "The server did not answer (\(failure.status)). Trying again.", line: "upload: retry, \(step) \(failure.status)")
        }
    }

    // ------------------------------------------------------------ the phone

    private var indexFile: URL {
        folder.appendingPathComponent("index.json")
    }

    nonisolated static func fileName(_ photoId: String) -> String {
        "\(photoId).jpg"
    }

    private func file(_ photoId: String) -> URL {
        folder.appendingPathComponent(Outbox.fileName(photoId))
    }

    private func save() {
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try JSONEncoder().encode(index).write(to: indexFile, options: .atomic)
        } catch {
            trail.mark("upload: the queue could not be kept (\(Auth.kind(error)))")
        }
    }

    /// Off the phone: the server has it, or it was refused and dropped.
    private func forget(_ photoId: String) {
        index.items.removeAll { $0.id == photoId }
        try? FileManager.default.removeItem(at: file(photoId))
        save()
    }

    private func refuse(_ photoId: String, _ why: String) {
        if let at = index.items.firstIndex(where: { $0.id == photoId }) {
            index.items[at].failed = why
        }
        states[photoId] = .failed(why)
        save()
    }

    // ------------------------------------------------------------ the flow

    private var flowFile: URL {
        folder.appendingPathComponent("flow.json")
    }

    nonisolated static func thumbName(_ photoId: String) -> String {
        "\(photoId).thumb"
    }

    /// A new flow, at "Send": its photos' small pictures first, then the
    /// flow that names them.
    private func startFlow(encounterId: String, photos: [Chosen]) {
        endFlow()
        for photo in photos {
            if let small = photo.thumb.jpegData(compressionQuality: 0.7) {
                try? small.write(to: folder.appendingPathComponent(Outbox.thumbName(photo.id)), options: .atomic)
            }
            flowThumbs[photo.id] = photo.thumb
        }
        keepFlow(ScanFlow(encounterId: encounterId, photos: photos.map { ScanFlow.Shot(id: $0.id, gallery: $0.gallery) }))
    }

    /// The flow as the screen changed it, kept at once.
    func keepFlow(_ changed: ScanFlow) {
        flow = changed
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try JSONEncoder().encode(changed).write(to: flowFile, options: .atomic)
        } catch {
            trail.mark("scan: the flow could not be kept (\(Auth.kind(error)))")
        }
    }

    /// The flow is over: what was kept for it leaves the phone.
    func endFlow() {
        flow = nil
        flowThumbs = [:]
        dropRefused(keeping: nil)
        try? FileManager.default.removeItem(at: flowFile)
        let files = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        for name in files where name.hasSuffix(".thumb") {
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(name))
        }
    }

    /// Forgets the encounters kept only for a post refused for good (nothing
    /// of them waits), but for `encounterId`'s, whose flow still shows it.
    private func dropRefused(keeping encounterId: String?) {
        let waiting = Set(index.items.map(\.encounterId))
        let gone = index.encounters.filter { encounter in
            guard let after = encounter.after, after.postFailed != nil, !after.pending else { return false }
            return encounter.id != encounterId && !waiting.contains(encounter.id)
        }.map(\.id)
        guard !gone.isEmpty else { return }
        index.encounters.removeAll { gone.contains($0.id) }
        for id in gone {
            posts[id] = nil
        }
        save()
    }

    /// The flow the last launch left, checked before it is used: one that
    /// is not whole is dropped, and the tab opens empty.
    private func openFlow() {
        guard let data = try? Data(contentsOf: flowFile) else { return }
        guard let kept = ScanFlow.read(data) else {
            trail.mark("scan: kept flow dropped, not whole")
            endFlow()
            return
        }
        flow = kept
        trail.mark("scan: kept flow back (\(kept.step.rawValue))")
        // Posted or added, and nothing of it left waiting or refused here:
        // it reached the server, and its encounter, done, was forgotten.
        if kept.ended, posts[kept.encounterId] == nil {
            posts[kept.encounterId] = .sent
        }
        let folder = self.folder
        for shot in kept.photos {
            Task.detached(priority: .utility) {
                let small = UIImage(contentsOfFile: folder.appendingPathComponent(Outbox.thumbName(shot.id)).path)
                await MainActor.run { self.setFlowThumb(shot.id, small) }
            }
        }
    }

    private func setFlowThumb(_ photoId: String, _ thumb: UIImage?) {
        if let thumb, flow?.photos.contains(where: { $0.id == photoId }) == true {
            flowThumbs[photoId] = thumb
        }
    }

    private func progressed(_ photoId: String, _ value: Double) {
        if case .sending = states[photoId] {
            states[photoId] = .sending(value)
        }
    }

    private func setThumb(_ photoId: String, _ thumb: UIImage?) {
        if let at = batch.firstIndex(where: { $0.id == photoId }) {
            batch[at].thumb = thumb
        }
    }
}

/// A photo chosen on the Scan screen and not sent yet.
struct Chosen: Identifiable {
    let id: String
    /// JPEG, 20 MB at most.
    let jpeg: Data
    let thumb: UIImage
    let gallery: Bool
    let capturedAt: Date?
    /// Where the phone was when it was taken. Always nil from the gallery.
    let place: Fix?
}

/// Small copies of pictures, for the grid.
enum Shrink {
    static func thumb(_ image: UIImage) -> UIImage {
        let side: CGFloat = 300
        let scale = min(1, side / max(1, min(image.size.width, image.size.height)))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }
}
