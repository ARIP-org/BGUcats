import Foundation

/// The member API (`/api/v1`, docs/app-plan/04-api.md), as far as this app
/// uses it yet.
protocol Backend {
    /// The caller's account. The app asks this first, always.
    func me() async throws -> Me
    func feed(cursor: String?) async throws -> FeedPage
    /// Likes or unlikes; answers with the post's new count.
    func like(postId: String, on: Bool) async throws -> Int

    // The capture flow (docs/app-plan/04-api.md, "The capture flow", rows
    // 1 to 4), on the desk's API as the web app's upload queue calls it.
    // Every call is safe to repeat: the ids are made on the phone.

    // Each answers the HTTP status it got, for the trail.

    /// `POST /api/encounters`: the encounter, with its place if it has one.
    func createEncounter(id: String, place: Fix?) async throws -> Int
    /// `POST /api/encounters/{id}/media`: the photo's record as `pending`,
    /// and where to upload its bytes.
    func startPhoto(_ photo: PhotoStart) async throws -> Started
    /// The bytes, to the presigned POST. `progress` hears 0 to 1.
    func upload(_ file: URL, to target: Presigned, progress: @escaping @Sendable (Double) -> Void) async throws -> Int
    /// `POST /api/photos/{id}/complete`: the server confirms the file.
    func complete(photoId: String) async throws -> Int

    /// The author removes their own post.
    func deletePost(postId: String) async throws
    /// Reports a thing. `reportId` is made once on the phone, so a retry is
    /// the same report. The server answers the same whatever it did.
    func report(_ report: Report) async throws
}

/// A report as the API takes it (`POST /api/v1/reports`).
struct Report: Equatable {
    let reportId: String
    /// `post` here; the API also takes `user`, `avatar` and `name`.
    let targetType: String
    let targetId: String
    let reason: ReportReason
    let note: String?
}

/// What `startPhoto` answered. No target: the server has the bytes already
/// (a retry after a lost answer).
struct Started {
    let status: Int
    let target: Presigned?
}

/// What `startPhoto` sends. A gallery photo sends no place at all.
struct PhotoStart {
    let encounterId: String
    let photoId: String
    let capturedAt: Date?
    let gallery: Bool
    let place: Fix?

    var body: [String: Any] {
        var body: [String: Any] = [
            "photoId": photoId,
            "contentType": "image/jpeg",
            "origin": gallery ? "gallery" : "camera",
        ]
        if let capturedAt {
            body["capturedAt"] = ISO8601DateFormatter().string(from: capturedAt)
        }
        if !gallery, let place {
            body["lat"] = place.lat
            body["lon"] = place.lon
            body["accuracyM"] = place.accuracyM
        }
        return body
    }
}

/// A presigned POST: the address and the form fields that go before the file.
struct Presigned {
    let url: URL
    let fields: [String: String]
}

/// What a call failed with. `status` 0: the server was not reached.
struct ApiError: Error, Equatable {
    let status: Int
    /// The API's machine word (`not_admitted`, `terms_required`, ...).
    let code: String?
    /// Words for a person.
    let message: String
}

final class LiveBackend: Backend {
    private let auth: Auth
    private let trail: Trail

    init(auth: Auth, trail: Trail) {
        self.auth = auth
        self.trail = trail
    }

    func me() async throws -> Me {
        let json = try await call("GET", "/me", as: "me")
        guard let me = Read.me(json) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        return me
    }

    func feed(cursor: String?) async throws -> FeedPage {
        Read.page(try await call("GET", "/feed", cursor: cursor, as: "feed"))
    }

    func like(postId: String, on: Bool) async throws -> Int {
        let json = try await call(on ? "PUT" : "DELETE", "/posts/\(Auth.encode(postId))/like", as: on ? "like" : "unlike")
        return Read.int(json["likes"])
    }

    func deletePost(postId: String) async throws {
        _ = try await call("DELETE", "/posts/\(Auth.encode(postId))", as: "delete post")
    }

    func report(_ report: Report) async throws {
        var body: [String: Any] = [
            "reportId": report.reportId,
            "targetType": report.targetType,
            "targetId": report.targetId,
            "reason": report.reason.rawValue,
        ]
        if let note = report.note {
            body["note"] = note
        }
        _ = try await call("POST", "/reports", body: body, as: "report")
    }

    func createEncounter(id: String, place: Fix?) async throws -> Int {
        var body: [String: Any] = ["sessionId": id]
        if let place {
            body["lat"] = place.lat
            body["lon"] = place.lon
            body["accuracyM"] = place.accuracyM
        }
        return try await exchange("POST", "/encounters", base: "/api", body: body, as: "encounter", quiet: true).status
    }

    func startPhoto(_ photo: PhotoStart) async throws -> Started {
        let (status, json) = try await exchange(
            "POST", "/encounters/\(Auth.encode(photo.encounterId))/media",
            base: "/api", body: photo.body, as: "media", quiet: true
        )
        if (json["done"] as? Bool) == true {
            return Started(status: status, target: nil)
        }
        let upload = json["upload"] as? [String: Any]
        guard let address = Read.url(upload?["url"]) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        var fields: [String: String] = [:]
        for (name, value) in (upload?["fields"] as? [String: Any]) ?? [:] {
            fields[name] = "\(value)"
        }
        return Started(status: status, target: Presigned(url: address, fields: fields))
    }

    func upload(_ file: URL, to target: Presigned, progress: @escaping @Sendable (Double) -> Void) async throws -> Int {
        let boundary = "bgucats-\(UUID().uuidString)"
        // Up to 20 MB, read and wrapped away from the screen's thread.
        let form = try await Task.detached(priority: .utility) {
            try LiveBackend.form(target.fields, file: file, boundary: boundary)
        }.value
        var request = URLRequest(url: target.url)
        request.httpMethod = "POST"
        // 20 MB on a slow link is minutes; a stalled one still gives up.
        request.timeoutInterval = 180
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "content-type")
        let response: URLResponse
        do {
            (_, response) = try await URLSession.shared.upload(for: request, from: form, delegate: UploadProgress(progress))
        } catch {
            throw ApiError(status: 0, code: Auth.kind(error), message: "The upload did not reach storage.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw ApiError(status: status, code: "storage", message: "Storage refused the upload (\(status)).")
        }
        return status
    }

    func complete(photoId: String) async throws -> Int {
        try await exchange("POST", "/photos/\(Auth.encode(photoId))/complete", base: "/api", body: [:], as: "complete", quiet: true).status
    }

    /// A presigned POST's body: its fields, then the file, which S3 wants last.
    static func form(_ fields: [String: String], file: URL, boundary: String) throws -> Data {
        var form = Data()
        func line(_ text: String) {
            form.append(Data((text + "\r\n").utf8))
        }
        for name in fields.keys.sorted() {
            line("--\(boundary)")
            line("Content-Disposition: form-data; name=\"\(name)\"")
            line("")
            line(fields[name] ?? "")
        }
        line("--\(boundary)")
        line("Content-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\"")
        line("Content-Type: image/jpeg")
        line("")
        form.append(try Data(contentsOf: file))
        line("")
        line("--\(boundary)--")
        return form
    }

    /// One call. `name` is what the trail calls it: the kind of call, never
    /// its address, which can carry an id. `quiet`: the caller marks the
    /// trail itself (the upload queue, which says "upload: media 200").
    private func call(_ method: String, _ path: String, cursor: String? = nil, body: [String: Any]? = nil, as name: String) async throws -> [String: Any] {
        try await exchange(method, path, cursor: cursor, body: body, as: name).json
    }

    /// `call`, answering the status too, on either API (`base`), with a
    /// JSON body if there is one.
    private func exchange(
        _ method: String,
        _ path: String,
        base: String = "/api/v1",
        cursor: String? = nil,
        body: [String: Any]? = nil,
        as name: String,
        quiet: Bool = false
    ) async throws -> (status: Int, json: [String: Any]) {
        let token: String
        switch await auth.pass() {
        case .token(let fresh):
            token = fresh
        case .signedOut:
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        case .notNow:
            throw ApiError(status: 0, code: nil, message: "The server could not be reached. Check the connection and try again.")
        }
        var address = Site.origin.absoluteString + base + path
        if let cursor {
            address += "?cursor=" + Auth.encode(cursor)
        }
        guard let url = URL(string: address) else {
            throw ApiError(status: 0, code: nil, message: "The request could not be made.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        // A request that hangs on a weak signal must not hold a screen for
        // ever. API Gateway gives up at thirty seconds anyway.
        request.timeoutInterval = 20
        request.setValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        if let body {
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "content-type")
        }

        let began = Date()
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            if !quiet {
                trail.mark("api: \(name) not reached (\(Auth.kind(error)))")
            }
            throw ApiError(status: 0, code: Auth.kind(error), message: "The server could not be reached. Check the connection and try again.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if !quiet {
            trail.mark("api: \(name) \(status) in \(Int(Date().timeIntervalSince(began) * 1000)) ms")
        }

        let json = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
        if status == 401 {
            // The server no longer takes this token. The tabs must not
            // stay up over calls that can only fail: the session is told.
            auth.ended("the API answered 401")
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        }
        guard (200..<300).contains(status) else {
            throw ApiError(
                status: status,
                code: json["code"] as? String,
                message: (json["error"] as? String) ?? "The request failed (\(status))."
            )
        }
        return (status, json)
    }
}

/// Hears how much of an upload's body has gone.
private final class UploadProgress: NSObject, URLSessionTaskDelegate {
    private let report: @Sendable (Double) -> Void

    init(_ report: @escaping @Sendable (Double) -> Void) {
        self.report = report
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didSendBodyData bytesSent: Int64,
        totalBytesSent: Int64,
        totalBytesExpectedToSend: Int64
    ) {
        guard totalBytesExpectedToSend > 0 else { return }
        report(Double(totalBytesSent) / Double(totalBytesExpectedToSend))
    }
}

/// For UI tests: a made-up member and three made-up posts, the same every
/// time; the member wrote the second. No network. The capture routes are
/// played, and what they were asked is kept in `record` for the test to read
/// (App info shows it).
final class StandInBackend: Backend {
    private let start: Date
    private let gate: StandInGate
    /// The test asked for a sign-in that ends at the first like.
    private let ends: Bool
    /// "-uploadFailsOnce": the second photo's upload times out once.
    private let failsOnce: Bool
    /// "-offline": no capture call reaches the server.
    private let offline: Bool
    private var liked: Set<String> = []
    private var failed = false
    private let lock = NSLock()
    /// Photos by the order they were first recorded in, so the record says
    /// "photo 2", never an id.
    private var numbers: [String: Int] = [:]
    private var kept: [String] = []
    private var deleted: Set<String> = []
    /// What was reported, for a test that wants to know.
    private(set) var reports: [Report] = []

    init(start: Date, gate: StandInGate, ends: Bool = false, failsOnce: Bool = false, offline: Bool = false) {
        self.start = start
        self.gate = gate
        self.ends = ends
        self.failsOnce = failsOnce
        self.offline = offline
    }

    /// One line per capture call, in the order they came: "encounter
    /// place", "media 1 camera place", "upload 1", "complete 1".
    var record: [String] {
        lock.lock()
        defer { lock.unlock() }
        return kept
    }

    private func keep(_ line: String) {
        lock.lock()
        defer { lock.unlock() }
        kept.append(line)
    }

    private func number(_ photoId: String) -> Int {
        lock.lock()
        defer { lock.unlock() }
        if let known = numbers[photoId] {
            return known
        }
        numbers[photoId] = numbers.count + 1
        return numbers.count
    }

    private func reach() async throws {
        // A moment, as a phone's link takes, so the screen shows progress.
        try? await Task.sleep(for: .milliseconds(150))
        if offline {
            throw ApiError(status: 0, code: "no connection", message: "The server could not be reached. Check the connection and try again.")
        }
    }

    func createEncounter(id: String, place: Fix?) async throws -> Int {
        try await reach()
        keep("encounter \(place == nil ? "no-place" : "place")")
        return 200
    }

    func startPhoto(_ photo: PhotoStart) async throws -> Started {
        try await reach()
        let body = photo.body
        let placed = body["lat"] != nil || body["lon"] != nil
        keep("media \(number(photo.photoId)) \((body["origin"] as? String) ?? "none") \(placed ? "place" : "no-place")")
        return Started(status: 200, target: Presigned(url: URL(string: "standin://storage/\(photo.photoId)")!, fields: [:]))
    }

    func upload(_ file: URL, to target: Presigned, progress: @escaping @Sendable (Double) -> Void) async throws -> Int {
        try await reach()
        let photo = number(target.url.lastPathComponent)
        if failsOnce && photo == 2 {
            let first = lock.withLock { () -> Bool in
                defer { failed = true }
                return !failed
            }
            if first {
                progress(0.4)
                try? await Task.sleep(for: .milliseconds(300))
                keep("upload \(photo) timed out")
                throw ApiError(status: 0, code: "timed out", message: "The upload did not reach storage.")
            }
        }
        guard FileManager.default.fileExists(atPath: file.path) else {
            throw ApiError(status: 0, code: "no file", message: "The photo is not on the phone.")
        }
        for step in 1...4 {
            progress(Double(step) / 4)
            try? await Task.sleep(for: .milliseconds(80))
        }
        keep("upload \(photo)")
        return 204
    }

    func complete(photoId: String) async throws -> Int {
        try await reach()
        keep("complete \(number(photoId))")
        return 200
    }

    func me() async throws -> Me {
        Me(
            userId: "u-test",
            username: "test.member",
            displayName: "Test Member",
            avatar: nil,
            role: "user",
            catsMet: 7,
            encounters: 12,
            termsRequired: false
        )
    }

    func feed(cursor: String?) async throws -> FeedPage {
        func photo(_ name: String) -> Photo {
            let url = URL(string: "standin://photo/\(name)")
            return Photo(id: name, thumb: url, medium: url)
        }
        func person(_ id: String, _ name: String, _ username: String) -> Person {
            Person(userId: id, username: username, displayName: name, avatar: nil)
        }
        let posts = [
            Post(
                id: "p1",
                author: person("u-a", "First Tester", "first.tester"),
                catName: "Mitzi",
                photos: [photo("a1"), photo("a2")],
                text: "By the library steps again, asleep in the sun.",
                likes: 3,
                liked: liked.contains("p1"),
                createdAt: start.addingTimeInterval(-2 * 3600),
                mine: false,
                state: nil
            ),
            Post(
                id: "p2",
                author: person("u-test", "Test Member", "test.member"),
                catName: nil,
                photos: [photo("b1")],
                text: "",
                likes: 0,
                liked: liked.contains("p2"),
                createdAt: start.addingTimeInterval(-26 * 3600),
                mine: true,
                state: "pending"
            ),
            Post(
                id: "p3",
                author: person("u-b", "Second Tester", "second.tester"),
                catName: "Shachor",
                photos: [photo("c1")],
                text: "Let me close enough for one photo.",
                likes: 11,
                liked: true,
                createdAt: start.addingTimeInterval(-3 * 86400),
                mine: false,
                state: nil
            ),
        ]
        return FeedPage(posts: posts.filter { !deleted.contains($0.id) }, cursor: nil)
    }

    func like(postId: String, on: Bool) async throws -> Int {
        if ends {
            // What LiveBackend does with a 401.
            gate.ended()
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        }
        if on {
            liked.insert(postId)
        } else {
            liked.remove(postId)
        }
        return postId == "p1" ? (on ? 4 : 3) : (on ? 1 : 0)
    }

    func deletePost(postId: String) async throws {
        // As the API: only the author may.
        guard postId == "p2" else {
            throw ApiError(status: 403, code: "not_yours", message: "This is not your post.")
        }
        deleted.insert(postId)
    }

    func report(_ report: Report) async throws {
        reports.append(report)
    }
}
