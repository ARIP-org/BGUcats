import SwiftUI
import UIKit

/// The upload queue: the web app's (web/outbox.js), for this app. What is
/// sent is written to the phone first (each photo's file, once, and a small
/// index beside them) and uploaded from there, so a dead spot on campus or a
/// closed app never loses a photo: the queue goes on at the next launch.
/// Nothing leaves the phone's storage until the server has confirmed it.
///
/// Every id is a ULID made here, so a retry after a lost answer lands on the
/// same records. The write order is the web app's: the encounter (with its
/// first photo, never empty), then for each photo its record as `pending`,
/// its bytes, and the confirmation. A photo never goes before its
/// encounter, and one photo's failure never holds up the others.
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
        index.encounters.removeAll { encounter in !kept.contains { $0.encounterId == encounter.id } }
        save()
        guard !index.items.isEmpty else { return }

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
    func send(_ photos: [Chosen], lateFix: Fix?) async throws {
        guard !photos.isEmpty else { return }
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
        let encounter = Encounter(id: ULID.make(), place: place, created: false)
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
        kick()
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

    /// "Scan another cat": the batch leaves the screen, and photos refused
    /// for good leave the phone.
    func clear() {
        for item in index.items where item.failed != nil {
            forget(item.id)
        }
        save()
        batch = []
        states = [:]
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
        let left = index.items
        index.encounters.removeAll { encounter in
            encounter.created && !left.contains { $0.encounterId == encounter.id }
        }
        save()
        return stuck || later
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

/// A ULID: 48 bits of milliseconds, 80 random bits, Crockford's base 32,
/// as web/outbox.js makes them. Sorts by time.
enum ULID {
    private static let alphabet = Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    static func make(now: Date = Date()) -> String {
        var millis = UInt64(max(0, now.timeIntervalSince1970 * 1000))
        var time = ""
        for _ in 0..<10 {
            time = String(alphabet[Int(millis % 32)]) + time
            millis /= 32
        }
        var generator = SystemRandomNumberGenerator()
        let rest = (0..<16).map { _ in String(alphabet[Int.random(in: 0..<32, using: &generator)]) }.joined()
        return time + rest
    }
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
