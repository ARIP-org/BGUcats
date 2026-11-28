import Foundation

/// The member API (`/api/v1`, docs/app-plan/04-api.md), as far as this app
/// uses it yet.
protocol Backend {
    /// The caller's account. The app asks this first, always.
    func me() async throws -> Me
    func feed(cursor: String?) async throws -> FeedPage
    /// Likes or unlikes; answers with the post's new count.
    func like(postId: String, on: Bool) async throws -> Int
    /// Accepts the terms of this version (`Me.termsCurrent`); answers with
    /// the account as it is now.
    func acceptTerms(version: String) async throws -> Me

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

    // What follows the photos (rows 6, 8 and 9), once every photo of the
    // encounter is confirmed.

    /// `POST /api/encounters/{id}/pick`: which cat the member said it was.
    func pick(encounterId: String, _ pick: PickBody) async throws -> Int
    /// `POST /api/v1/proposals`: "A cat that isn't here". Sent again with
    /// the same `proposalId`, it is the same proposal.
    func propose(_ proposal: ProposalBody) async throws -> Int
    /// `POST /api/v1/posts`: the post. Sent again with the same `postId`,
    /// it is the same post.
    func post(_ post: PostBody) async throws -> Int

    /// `GET /api/v1/cats`: every public cat, for "Which cat?".
    func cats() async throws -> [Cat]
    /// `GET /api/v1/cats` whole: the cats and today's cat of the day, for
    /// the gallery.
    func catList() async throws -> CatList
    /// `GET /api/v1/cats/{catId}`: a cat's page.
    func cat(id: String) async throws -> CatDetail
    /// `GET /api/v1/cats/{catId}/posts`: the cat's visible posts, newest
    /// first, as the feed's cards.
    func catPosts(id: String, cursor: String?) async throws -> FeedPage

    // The name poll on a cat's page (docs/app-plan/04-api.md). Each answers
    // with the poll as it is now, the same as `names` would.

    /// `GET /api/v1/cats/{catId}/names`.
    func names(catId: String) async throws -> Poll
    /// `POST /api/v1/cats/{catId}/names` `{name}`: a name for the poll, with
    /// the caller's vote. One that is already an option is a vote for it.
    func suggest(catId: String, name: String) async throws -> Poll
    /// `PUT /api/v1/cats/{catId}/vote` `{nameKey}`: the caller's one vote,
    /// moved to this option.
    func vote(catId: String, nameKey: String) async throws -> Poll
    /// `DELETE /api/v1/cats/{catId}/vote`: taken back.
    func unvote(catId: String) async throws -> Poll

    // The member's own account (docs/app-plan/04-api.md, "Me").

    /// `PATCH /me` `{displayName}`: the account as it is now, the new name
    /// `namePending` until it has been checked. Needs the terms.
    func rename(_ displayName: String) async throws -> Me
    /// `PUT /me/username` `{username}`: the account as it is now. Needs the
    /// terms; `bad_username` and `name_taken` refuse it.
    func chooseUsername(_ username: String) async throws -> Me
    /// `GET /me/posts`: the member's posts, those others cannot see
    /// included, each with its state. One page: the server sends them all.
    func myPosts() async throws -> FeedPage
    /// `DELETE /me` `{"confirm": confirm}`, which the server takes only as
    /// "delete". True when it answered `{"deleting": true}`.
    func deleteAccount(confirm: String) async throws -> Bool

    // The profile photo (docs/app-plan/04-api.md, the three avatar rows):
    // where to send it, the bytes, the confirmation; and removing it.

    /// `POST /me/avatar`: an avatar id, and a presigned upload pinned to
    /// the member's own key, to JPEG and to 200 KB. Needs the terms; five
    /// a day (`rate_limited`).
    func startAvatar() async throws -> AvatarStart
    /// The JPEG (`Avatar.ready`) to that upload. Answers storage's status.
    func uploadAvatar(_ jpeg: Data, to target: Presigned) async throws -> Int
    /// `POST /me/avatar/{avatarId}/complete`: the account as it is now,
    /// the new photo `avatarPending` until it has been checked.
    /// `bad_photo`: not a JPEG, or one that still carries EXIF, XMP or IPTC.
    func completeAvatar(avatarId: String) async throws -> Me
    /// `DELETE /me/avatar`: the account with no photo.
    func removeAvatar() async throws -> Me

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

/// A member's answer to "Which cat?", as `_record_pick` in
/// src/admin/handler.py takes it from an app with no model: the cat chosen
/// is the one cat shown, the ranking is empty, and the model is "none"
/// (`NO_MODEL` in web/social/scan.js). "Not sure" sends no pick at all:
/// with nothing ranked nothing was shown, and the server refuses a pick
/// that shows nothing (as the web app sends none).
struct PickBody: Codable, Equatable {
    static let noModel = "none"

    let catId: String
    let photoCount: Int

    var body: [String: Any] {
        [
            "modelVersion": PickBody.noModel,
            "choice": "cat",
            "catId": catId,
            "shown": [catId],
            "ranked": [Any](),
            "photoCount": max(1, photoCount),
        ]
    }
}

/// A new-cat proposal as `POST /api/v1/proposals` takes it
/// (docs/app-plan/04-api.md). `proposalId` is made once on the phone, so
/// sending it again is the same proposal; it becomes the cat's id if an
/// admin approves it. An answer not given is left out.
struct ProposalBody: Codable, Equatable {
    let proposalId: String
    let sessionId: String
    let nameIdea: String?
    let coat: String?
    /// A campus place's id, or "elsewhere".
    let regionId: String?
    let traits: [String]

    var body: [String: Any] {
        var body: [String: Any] = [
            "proposalId": proposalId,
            "sessionId": sessionId,
        ]
        if let nameIdea, !nameIdea.isEmpty {
            body["nameIdea"] = nameIdea
        }
        if let coat {
            body["coat"] = coat
        }
        if let regionId {
            body["regionId"] = regionId
        }
        if !traits.isEmpty {
            body["traits"] = traits
        }
        return body
    }
}

/// A post as `POST /api/v1/posts` takes it (docs/app-plan/04-api.md).
/// `postId` is made once on the phone, so sending it again is the same post.
struct PostBody: Codable, Equatable {
    let postId: String
    let sessionId: String
    /// Every photo of the encounter, in the order they were taken.
    var photoIds: [String]
    /// The cat chosen; nil for "Not sure" and for a new cat.
    let catId: String?
    /// The new cat's proposal, which goes first. Absent from a post kept
    /// before this existed.
    let proposalId: String?
    let text: String?
    let shareRegion: Bool

    var body: [String: Any] {
        var body: [String: Any] = [
            "postId": postId,
            "sessionId": sessionId,
            "photoIds": photoIds,
            "claim": catId.map { ["catId": $0] as Any } ?? proposalId.map { ["proposalId": $0] as Any } ?? NSNull(),
            "shareRegion": shareRegion,
        ]
        if let text, !text.isEmpty {
            body["text"] = text
        }
        return body
    }
}

/// What `POST /me/avatar` answered.
struct AvatarStart: Equatable {
    let avatarId: String
    let target: Presigned
}

/// A presigned POST: the address and the form fields that go before the file.
struct Presigned: Equatable {
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

    func acceptTerms(version: String) async throws -> Me {
        let json = try await call("POST", "/me/terms", body: ["version": version], as: "terms")
        guard let me = Read.me(json) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        return me
    }

    func deletePost(postId: String) async throws {
        _ = try await call("DELETE", "/posts/\(Auth.encode(postId))", as: "delete post")
    }

    func rename(_ displayName: String) async throws -> Me {
        try LiveBackend.me(try await call("PATCH", "/me", body: ["displayName": displayName], as: "rename"))
    }

    func chooseUsername(_ username: String) async throws -> Me {
        try LiveBackend.me(try await call("PUT", "/me/username", body: ["username": username], as: "username"))
    }

    func myPosts() async throws -> FeedPage {
        let page = Read.page(try await call("GET", "/me/posts", as: "my posts"))
        return FeedPage(posts: page.posts, cursor: nil)
    }

    func deleteAccount(confirm: String) async throws -> Bool {
        let json = try await call("DELETE", "/me", body: ["confirm": confirm], as: "delete account")
        return (json["deleting"] as? Bool) == true
    }

    func startAvatar() async throws -> AvatarStart {
        let json = try await call("POST", "/me/avatar", body: [:], as: "avatar")
        let upload = json["upload"] as? [String: Any]
        guard let avatarId = json["avatarId"] as? String, let address = Read.url(upload?["url"]) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        var fields: [String: String] = [:]
        for (name, value) in (upload?["fields"] as? [String: Any]) ?? [:] {
            fields[name] = "\(value)"
        }
        return AvatarStart(avatarId: avatarId, target: Presigned(url: address, fields: fields))
    }

    func uploadAvatar(_ jpeg: Data, to target: Presigned) async throws -> Int {
        let boundary = "bgucats-\(UUID().uuidString)"
        var request = URLRequest(url: target.url)
        request.httpMethod = "POST"
        // 200 KB at most: it gives up as every call does.
        request.timeoutInterval = 20
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "content-type")
        let began = Date()
        let response: URLResponse
        do {
            (_, response) = try await URLSession.shared.upload(
                for: request, from: LiveBackend.form(target.fields, data: jpeg, boundary: boundary)
            )
        } catch {
            trail.mark("api: avatar upload not reached (\(Auth.kind(error)))")
            throw ApiError(status: 0, code: Auth.kind(error), message: "The photo did not reach storage. Check the connection and try again.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        trail.mark("api: avatar upload \(status) in \(Int(Date().timeIntervalSince(began) * 1000)) ms")
        guard (200..<300).contains(status) else {
            throw ApiError(status: status, code: "storage", message: "Storage refused the photo (\(status)).")
        }
        return status
    }

    func completeAvatar(avatarId: String) async throws -> Me {
        try LiveBackend.me(try await call("POST", "/me/avatar/\(Auth.encode(avatarId))/complete", body: [:], as: "avatar complete"))
    }

    func removeAvatar() async throws -> Me {
        try LiveBackend.me(try await call("DELETE", "/me/avatar", as: "remove avatar"))
    }

    private static func me(_ json: [String: Any]) throws -> Me {
        guard let me = Read.me(json) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        return me
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
            try LiveBackend.form(target.fields, data: Data(contentsOf: file), boundary: boundary)
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

    func pick(encounterId: String, _ pick: PickBody) async throws -> Int {
        try await exchange("POST", "/encounters/\(Auth.encode(encounterId))/pick", base: "/api", body: pick.body, as: "pick", quiet: true).status
    }

    func propose(_ proposal: ProposalBody) async throws -> Int {
        try await exchange("POST", "/proposals", body: proposal.body, as: "proposal", quiet: true).status
    }

    func post(_ post: PostBody) async throws -> Int {
        try await exchange("POST", "/posts", body: post.body, as: "post", quiet: true).status
    }

    func cats() async throws -> [Cat] {
        try await catList().cats
    }

    func catList() async throws -> CatList {
        Read.catList(try await call("GET", "/cats", as: "cats"))
    }

    func cat(id: String) async throws -> CatDetail {
        let json = try await call("GET", "/cats/\(Auth.encode(id))", as: "cat")
        guard let cat = Read.catDetail(json) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        return cat
    }

    func catPosts(id: String, cursor: String?) async throws -> FeedPage {
        Read.page(try await call("GET", "/cats/\(Auth.encode(id))/posts", cursor: cursor, as: "cat posts"))
    }

    func names(catId: String) async throws -> Poll {
        try LiveBackend.poll(try await call("GET", "/cats/\(Auth.encode(catId))/names", as: "names"))
    }

    func suggest(catId: String, name: String) async throws -> Poll {
        try LiveBackend.poll(try await call("POST", "/cats/\(Auth.encode(catId))/names", body: ["name": name], as: "suggest"))
    }

    func vote(catId: String, nameKey: String) async throws -> Poll {
        try LiveBackend.poll(try await call("PUT", "/cats/\(Auth.encode(catId))/vote", body: ["nameKey": nameKey], as: "vote"))
    }

    func unvote(catId: String) async throws -> Poll {
        try LiveBackend.poll(try await call("DELETE", "/cats/\(Auth.encode(catId))/vote", as: "unvote"))
    }

    private static func poll(_ json: [String: Any]) throws -> Poll {
        guard let poll = Read.poll(json) else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        return poll
    }

    /// A presigned POST's body: its fields, then the file, which S3 wants last.
    static func form(_ fields: [String: String], data: Data, boundary: String) -> Data {
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
        form.append(data)
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
        if status == 403 && (json["code"] as? String) == "gone" {
            // The account is being deleted (`_require_usable`): every call
            // will answer this. The session ends, with its own sentence.
            auth.accountGone()
            throw ApiError(status: 403, code: "gone", message: Session.deletedNote)
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
    /// "-postNotReadyOnce": the first post is answered `not_ready`, as
    /// when a photo is still being processed.
    private let notReadyOnce: Bool
    private var answeredNotReady = false
    /// The posts made, newest first: the feed shows them above the rest.
    private var posted: [Post] = []
    private var liked: Set<String> = []
    /// The made-up member has accepted the terms ("-termsRequired": not).
    private var accepted: Bool
    /// "-termsChanged": the terms changed after the account was read, so
    /// the first `me()` says nothing is required and the first like is
    /// refused all the same.
    private var stale: Bool
    private var failed = false
    private let lock = NSLock()
    /// Photos by the order they were first recorded in, so the record says
    /// "photo 2", never an id.
    private var numbers: [String: Int] = [:]
    /// Proposals likewise, and the encounter each is for.
    private var proposals: [String: (number: Int, sessionId: String)] = [:]
    private var kept: [String] = []
    private var deleted: Set<String> = []
    /// What was reported, for a test that wants to know.
    private(set) var reports: [Report] = []
    /// The name polls, by cat (`StandInBackend.madeUpPolls`), and the
    /// member's vote on each.
    private var polls = StandInBackend.madeUpPolls
    private var votes: [String: String] = [:]
    /// The member's account as the profile changed it.
    private var displayName = "Test Member"
    private var username = "test.member"
    private var namePending = false
    /// The profile photo: the number of the picture shown (nil: none), and
    /// whether it waits to be checked. Pictures are numbered as they are
    /// started, so the record says "avatar 2", never an id.
    private var avatar: Int?
    private var avatarPending = false
    private var avatars: [String: Int] = [:]
    private var avatarBytes: [Int: Data] = [:]

    init(
        start: Date,
        gate: StandInGate,
        ends: Bool = false,
        termsRequired: Bool = false,
        termsChanged: Bool = false,
        failsOnce: Bool = false,
        offline: Bool = false,
        notReadyOnce: Bool = false
    ) {
        self.start = start
        self.gate = gate
        self.ends = ends
        self.accepted = !(termsRequired || termsChanged)
        self.stale = termsChanged
        self.failsOnce = failsOnce
        self.offline = offline
        self.notReadyOnce = notReadyOnce
    }

    /// The made-up campus: three cats, one of them with no name yet, no
    /// place, no coat, no description and no grade; the member met the
    /// first twice and the others never.
    static let campus = [
        Cat(
            id: "c1", name: "Mitzi", cover: URL(string: "standin://photo/cat-mitzi"),
            coverMedium: URL(string: "standin://photo/cat-mitzi"),
            nameSource: "poll", regionId: "library", coat: "calico", gpa: 4.0, posts: 1, likes: 3
        ),
        Cat(
            id: "c2", name: "Shachor", cover: URL(string: "standin://photo/cat-shachor"),
            coverMedium: URL(string: "standin://photo/cat-shachor"),
            nameSource: "admin", regionId: "engineering", coat: "black", gpa: 2.6, posts: 1, likes: 11
        ),
        Cat(
            id: "c3", name: nil, cover: URL(string: "standin://photo/cat-three"),
            coverMedium: URL(string: "standin://photo/cat-three"),
            nameSource: "none", posts: 0, likes: 0
        ),
    ]

    /// One option of a made-up poll. `order` stands for when it was
    /// suggested: the earlier wins a tie, as on the server.
    private struct Option {
        let key: String
        let name: String
        var votes: Int
        /// The member's own suggestion, not checked yet.
        var pending: Bool
        let order: Int
    }

    /// Mitzi's poll: her name leading, a second name behind it, and the
    /// member's own suggestion still being checked, which they voted for
    /// and have since taken the vote off. Shachor's: the admins' name,
    /// with no votes. The cat with no name: no option yet.
    private static let madeUpPolls: [String: [Option]] = [
        "c1": [
            Option(key: "mitzi", name: "Mitzi", votes: 5, pending: false, order: 0),
            Option(key: "pilpel", name: "Pilpel", votes: 2, pending: false, order: 1),
            Option(key: "ptitim", name: "Ptitim", votes: 0, pending: true, order: 2),
        ],
        "c2": [Option(key: "shachor", name: "Shachor", votes: 0, pending: false, order: 0)],
        "c3": [],
    ]

    /// The poll as `_names_view` answers it. Called under the lock.
    private func pollView(_ catId: String) -> Poll {
        let options = polls[catId] ?? []
        let mine = votes[catId]
        let live = options.filter { !$0.pending }.sorted { ($0.votes, -$0.order) > ($1.votes, -$1.order) }
        let leader = live.first { $0.votes > 0 }
        let shown = { (option: Option) in
            Poll.Option(
                nameKey: option.key, name: option.name, votes: option.votes,
                leading: option.key == leader?.key, mine: option.key == mine, pending: option.pending
            )
        }
        let admins = StandInBackend.campus.first { $0.id == catId }?.name
        return Poll(
            name: leader?.name ?? admins,
            nameSource: leader != nil ? "poll" : admins != nil ? "admin" : "none",
            options: live.map(shown) + options.filter(\.pending).map(shown),
            total: live.reduce(0) { $0 + $1.votes },
            locked: nil
        )
    }

    /// The member's vote moved to `key` (nil: taken back), as `_move_vote`.
    /// Called under the lock.
    private func move(_ catId: String, to key: String?) {
        let old = votes[catId]
        guard old != key, var options = polls[catId] else { return }
        for index in options.indices {
            if options[index].key == old {
                options[index].votes -= 1
            }
            if options[index].key == key {
                options[index].votes += 1
            }
        }
        polls[catId] = options
        votes[catId] = key
    }

    /// What `require_terms` refuses, refused here too.
    private func termsFirst() throws {
        if !accepted {
            stale = false
            throw ApiError(status: 403, code: "terms_required", message: "accept the terms first")
        }
    }

    func names(catId: String) async throws -> Poll {
        try await reach()
        return lock.withLock { pollView(catId) }
    }

    /// Recorded as "suggest Name, new" or "suggest Name, merged into key":
    /// the name as typed, so the test knows it went as written. Only the
    /// made-up server's record holds it, never the trail.
    func suggest(catId: String, name: String) async throws -> Poll {
        try await reach()
        try termsFirst()
        let cleaned = name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !cleaned.isEmpty, ScanFlow.length(cleaned) <= ScanFlow.nameLimit else {
            keep("suggest refused")
            throw ApiError(status: 400, code: nil, message: "name is longer than 24 characters")
        }
        let key = cleaned.lowercased()
        return lock.withLock { () -> Poll in
            guard polls[catId] != nil else { return pollView(catId) }
            if polls[catId]?.contains(where: { $0.key == key }) == true {
                kept.append("suggest \(cleaned), merged into \(key)")
            } else {
                let order = polls[catId]?.count ?? 0
                polls[catId]?.append(Option(key: key, name: cleaned, votes: 0, pending: true, order: order))
                kept.append("suggest \(cleaned), new")
            }
            move(catId, to: key)
            return pollView(catId)
        }
    }

    /// Recorded as "vote key" for a first vote and "vote key from old" for
    /// a vote moved.
    func vote(catId: String, nameKey: String) async throws -> Poll {
        try await reach()
        try termsFirst()
        return try lock.withLock { () -> Poll in
            guard polls[catId]?.contains(where: { $0.key == nameKey }) == true else {
                kept.append("vote gone")
                throw ApiError(status: 404, code: "gone", message: "no such name in this poll")
            }
            let old = votes[catId]
            if old != nameKey {
                kept.append(old.map { "vote \(nameKey) from \($0)" } ?? "vote \(nameKey)")
            }
            move(catId, to: nameKey)
            return pollView(catId)
        }
    }

    /// Recorded as "unvote key". Asks no terms, as the API.
    func unvote(catId: String) async throws -> Poll {
        try await reach()
        return lock.withLock { () -> Poll in
            if let old = votes[catId] {
                kept.append("unvote \(old)")
            }
            move(catId, to: nil)
            return pollView(catId)
        }
    }

    /// The campus with its dates, which hang on the stand-in's clock.
    private var dated: [Cat] {
        StandInBackend.campus.map { cat in
            var cat = cat
            switch cat.id {
            case "c1":
                cat.lastSeenAt = start.addingTimeInterval(-2 * 3600)
                cat.firstSeenAt = start.addingTimeInterval(-40 * 86400)
            case "c2":
                cat.lastSeenAt = start.addingTimeInterval(-3 * 86400)
                cat.firstSeenAt = start.addingTimeInterval(-90 * 86400)
            default:
                // Never seen since it was added: no "last seen" is sent.
                cat.firstSeenAt = start.addingTimeInterval(-5 * 86400)
            }
            return cat
        }
    }

    /// One line per capture call, in the order they came: "encounter
    /// place", "media 1 camera place", "upload 1", "complete 1", "pick c2
    /// shown c2 ranked 0", "proposal 1 name coat tabby region library
    /// traits friendly", "post not_ready", "post claim c2 photos 1 2 text
    /// region", "post proposal 1 photos 3 text region". A name idea is
    /// recorded as "name" or "no-name", never itself.
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

    func pick(encounterId: String, _ pick: PickBody) async throws -> Int {
        try await reach()
        let body = pick.body
        // What `_record_pick` refuses, refused here too.
        let shown = body["shown"] as? [String] ?? []
        let ranked = body["ranked"] as? [Any]
        guard !shown.isEmpty, ranked != nil, (body["choice"] as? String) == "cat",
              StandInBackend.campus.contains(where: { $0.id == pick.catId })
        else {
            keep("pick refused")
            throw ApiError(status: 400, code: nil, message: "shown must list 1 to 5 cat ids")
        }
        keep("pick \(pick.catId) shown \(shown.joined(separator: ",")) ranked \(ranked?.count ?? -1)")
        return 200
    }

    func propose(_ proposal: ProposalBody) async throws -> Int {
        try await reach()
        // What `_create_proposal` refuses, refused here too.
        let coatKnown = proposal.coat.map { coat in Campus.coats.contains { $0.id == coat } } ?? true
        let placeKnown = proposal.regionId.map { region in region == Campus.elsewhere.id || Campus.places.contains { $0.id == region } } ?? true
        let traitsKnown = proposal.traits.allSatisfy { trait in Campus.traits.contains { $0.id == trait } }
        guard ScanFlow.isUlid(proposal.proposalId), coatKnown, placeKnown, traitsKnown,
              (proposal.nameIdea ?? "").unicodeScalars.count <= ScanFlow.nameLimit
        else {
            keep("proposal refused")
            throw ApiError(status: 400, code: nil, message: "the new cat's answers are not ones the server takes")
        }
        let taken = lock.withLock { () -> Bool in
            proposals[proposal.proposalId] == nil && proposals.values.contains { $0.sessionId == proposal.sessionId }
        }
        if taken {
            keep("proposal already_proposed")
            throw ApiError(status: 409, code: "already_proposed", message: "this encounter has a proposal already")
        }
        let number = lock.withLock { () -> Int in
            if let known = proposals[proposal.proposalId] {
                return known.number
            }
            let made = proposals.count + 1
            proposals[proposal.proposalId] = (made, proposal.sessionId)
            return made
        }
        let name = (proposal.nameIdea ?? "").isEmpty ? "no-name" : "name"
        let traits = proposal.traits.isEmpty ? "none" : proposal.traits.joined(separator: ",")
        keep("proposal \(number) \(name) coat \(proposal.coat ?? "none") region \(proposal.regionId ?? "none") traits \(traits)")
        return 200
    }

    func post(_ post: PostBody) async throws -> Int {
        try await reach()
        var named: Int?
        if let proposalId = post.proposalId, post.catId == nil {
            // As `_claimed_proposal`: the post names a proposal the server has.
            named = lock.withLock { proposals[proposalId].flatMap { $0.sessionId == post.sessionId ? $0.number : nil } }
            if named == nil {
                keep("post refused, no such proposal")
                throw ApiError(status: 400, code: nil, message: "no such proposal for this encounter")
            }
        }
        let first = lock.withLock { () -> Bool in
            defer { answeredNotReady = true }
            return notReadyOnce && !answeredNotReady
        }
        if first {
            keep("post not_ready")
            throw ApiError(status: 425, code: "not_ready", message: "a photo is still uploading")
        }
        let photos = post.photoIds.map { "\(number($0))" }.joined(separator: " ")
        let words = (post.text ?? "").isEmpty ? "no-text" : "text"
        let claim = post.catId.map { "claim \($0)" } ?? named.map { "proposal \($0)" } ?? "no-claim"
        keep("post \(claim) photos \(photos) \(words) \(post.shareRegion ? "region" : "no-region")")
        let cat = StandInBackend.campus.first { $0.id == post.catId }
        let made = Post(
            id: post.postId,
            author: Person(userId: "u-test", username: "test.member", displayName: "Test Member", avatar: nil),
            catName: cat?.name,
            photos: post.photoIds.map { Photo(id: $0, thumb: URL(string: "standin://photo/\($0)"), medium: URL(string: "standin://photo/\($0)")) },
            text: post.text ?? "",
            likes: 0,
            liked: false,
            createdAt: start,
            mine: true,
            // The author sees their own post while it is being checked.
            state: "pending"
        )
        lock.withLock {
            if !posted.contains(where: { $0.id == made.id }) {
                posted.insert(made, at: 0)
            }
        }
        return 201
    }

    func cats() async throws -> [Cat] {
        StandInBackend.campus
    }

    func catList() async throws -> CatList {
        try await reach()
        return CatList(cats: dated, catOfTheDay: "c2")
    }

    func cat(id: String) async throws -> CatDetail {
        try await reach()
        guard let cat = dated.first(where: { $0.id == id }) else {
            throw ApiError(status: 404, code: "gone", message: "no such cat")
        }
        let photos = (1...3).map { index in
            let url = URL(string: "standin://photo/\(id)-\(index)")
            return Photo(id: "\(id)-\(index)", thumb: url, medium: url)
        }
        switch id {
        case "c1":
            let day = { (back: Double) in self.start.addingTimeInterval(-back * 86400) }
            return CatDetail(
                cat: cat,
                bio: "Sleeps on the library steps most afternoons. Likes a chin scratch, not a lap.",
                met: Met(encounters: 2, days: 2, firstDay: day(20), lastDay: day(1)),
                photos: photos
            )
        case "c2":
            return CatDetail(cat: cat, bio: "The black cat of the engineering building.", met: nil, photos: photos)
        default:
            return CatDetail(cat: cat, bio: nil, met: nil, photos: Array(photos.prefix(1)))
        }
    }

    func catPosts(id: String, cursor: String?) async throws -> FeedPage {
        try await reach()
        guard let name = StandInBackend.campus.first(where: { $0.id == id })?.name else {
            return FeedPage(posts: [], cursor: nil)
        }
        let made = lock.withLock { posted }
        return FeedPage(posts: (made + madeUp).filter { $0.catName == name && !deleted.contains($0.id) }, cursor: nil)
    }

    func me() async throws -> Me {
        lock.withLock {
            Me(
                userId: "u-test",
                username: username,
                displayName: displayName,
                avatar: avatar.map { URL(string: "standin://photo/avatar-\($0)")! },
                role: "user",
                catsMet: 7,
                encounters: 12,
                termsRequired: !accepted && !stale,
                termsCurrent: "draft",
                namePending: namePending,
                avatarPending: avatarPending
            )
        }
    }

    /// Recorded as "rename": the name itself only in the account. As the
    /// server, a new name is the member's at once and pending for others.
    func rename(_ displayName: String) async throws -> Me {
        try await reach()
        try termsFirst()
        let name = displayName.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !name.isEmpty, name.unicodeScalars.count <= 30 else {
            keep("rename refused")
            throw ApiError(status: 400, code: nil, message: "displayName is 1 to 30 characters")
        }
        lock.withLock {
            if name != self.displayName {
                kept.append("rename")
                self.displayName = name
                namePending = true
            }
        }
        return try await me()
    }

    /// The other made-up members' usernames are taken, as on the server.
    /// Recorded as "username ok", "username name_taken" or "username
    /// bad_username", never the name.
    func chooseUsername(_ username: String) async throws -> Me {
        try await reach()
        try termsFirst()
        let name = username.trimmingCharacters(in: .whitespaces).lowercased()
        let rule = #"^[a-z0-9](?:[a-z0-9]|[._](?=[a-z0-9])){1,18}[a-z0-9]$"#
        guard name.range(of: rule, options: .regularExpression) != nil else {
            keep("username bad_username")
            throw ApiError(status: 400, code: "bad_username", message: "a username is 3 to 20 letters a-z, digits, dots or underscores")
        }
        if ["first.tester", "second.tester", "admin"].contains(name) {
            keep("username name_taken")
            throw ApiError(status: 409, code: "name_taken", message: "that username is taken")
        }
        lock.withLock {
            kept.append("username ok")
            self.username = name
        }
        return try await me()
    }

    /// The member's posts as `_my_posts` answers them: the one being
    /// checked from the feed (until it is deleted), the posts made in this
    /// run, and an older public one the feed's page does not reach.
    func myPosts() async throws -> FeedPage {
        try await reach()
        let made = lock.withLock { posted }
        let old = Post(
            id: "p4",
            author: Person(userId: "u-test", username: "test.member", displayName: "Test Member", avatar: nil),
            catName: "Shachor",
            photos: [Photo(id: "d1", thumb: URL(string: "standin://photo/d1"), medium: URL(string: "standin://photo/d1"))],
            text: "Found him by the engineering doors.",
            likes: 5,
            liked: false,
            createdAt: start.addingTimeInterval(-9 * 86400),
            mine: true,
            state: "visible"
        )
        let own = (made + madeUp.filter(\.mine) + [old]).filter { !deleted.contains($0.id) }
        return FeedPage(posts: own, cursor: nil)
    }

    /// Recorded as "delete me confirm <what was sent>", so a test sees the
    /// body went as the server takes it, and how many times.
    func deleteAccount(confirm: String) async throws -> Bool {
        try await reach()
        keep("delete me confirm \(confirm)")
        guard confirm == "delete" else {
            throw ApiError(status: 400, code: "confirm", message: "confirm is \"delete\"")
        }
        return true
    }

    /// Recorded as "avatar start 1". Needs the terms, as the API.
    func startAvatar() async throws -> AvatarStart {
        try await reach()
        try termsFirst()
        let id = Ulid.make()
        let number = lock.withLock { () -> Int in
            let made = avatars.count + 1
            avatars[id] = made
            kept.append("avatar start \(made)")
            return made
        }
        return AvatarStart(avatarId: id, target: Presigned(url: URL(string: "standin://storage/avatar-\(number)")!, fields: [:]))
    }

    /// Recorded as what storage was sent, read from the bytes themselves:
    /// "avatar upload 1 jpeg 143201 bytes 512x512 metadata none". A file
    /// over 200 KB is refused, as the presigned POST's size range.
    func uploadAvatar(_ jpeg: Data, to target: Presigned) async throws -> Int {
        try await reach()
        let number = Int(target.url.lastPathComponent.split(separator: "-").last ?? "") ?? 0
        let kind = jpeg.starts(with: [0xFF, 0xD8, 0xFF]) ? "jpeg" : "not-jpeg"
        let size = Avatar.pixels(jpeg).map { "\($0.width)x\($0.height)" } ?? "unreadable"
        let metadata = Avatar.problem(jpeg) == nil ? "none" : "found"
        keep("avatar upload \(number) \(kind) \(jpeg.count) bytes \(size) metadata \(metadata)")
        guard jpeg.count <= Avatar.maxBytes else {
            throw ApiError(status: 400, code: "storage", message: "Storage refused the photo (400).")
        }
        lock.withLock { avatarBytes[number] = jpeg }
        return 204
    }

    /// Recorded as "avatar complete 1", or "avatar complete 2 bad_photo".
    /// As `_complete_avatar`: refused if the bytes are not a JPEG or still
    /// carry metadata. And the second picture of a launch is refused all
    /// the same, so a walk sees a refusal.
    func completeAvatar(avatarId: String) async throws -> Me {
        try await reach()
        let (number, bytes) = lock.withLock { () -> (Int, Data?) in
            let number = avatars[avatarId] ?? 0
            return (number, avatarBytes[number])
        }
        guard let bytes else {
            keep("avatar complete \(number) try_again")
            throw ApiError(status: 409, code: "try_again", message: "the photo has not reached storage yet")
        }
        if number == 2 || Avatar.problem(bytes) != nil {
            keep("avatar complete \(number) bad_photo")
            throw ApiError(status: 400, code: "bad_photo", message: "this photo cannot be a profile photo: it still carries EXIF or XMP data")
        }
        lock.withLock {
            kept.append("avatar complete \(number)")
            avatar = number
            avatarPending = true
        }
        return try await me()
    }

    /// Recorded as "avatar remove". Asks no terms, as the API.
    func removeAvatar() async throws -> Me {
        try await reach()
        lock.withLock {
            kept.append("avatar remove")
            avatar = nil
            avatarPending = false
        }
        return try await me()
    }

    func feed(cursor: String?) async throws -> FeedPage {
        let made = lock.withLock { posted }
        return FeedPage(posts: (made + madeUp).filter { !deleted.contains($0.id) }, cursor: nil)
    }

    /// The three made-up posts, as the member's likes left them.
    private var madeUp: [Post] {
        func photo(_ name: String) -> Photo {
            let url = URL(string: "standin://photo/\(name)")
            return Photo(id: name, thumb: url, medium: url)
        }
        func person(_ id: String, _ name: String, _ username: String) -> Person {
            Person(userId: id, username: username, displayName: name, avatar: nil)
        }
        return [
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
    }

    func like(postId: String, on: Bool) async throws -> Int {
        if ends {
            // What LiveBackend does with a 401.
            gate.ended()
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        }
        if on && !accepted {
            // What the API does (`require_terms`); the account read next
            // says so.
            stale = false
            throw ApiError(status: 403, code: "terms_required", message: "accept the terms first")
        }
        if on {
            liked.insert(postId)
        } else {
            liked.remove(postId)
        }
        return postId == "p1" ? (on ? 4 : 3) : (on ? 1 : 0)
    }

    func acceptTerms(version: String) async throws -> Me {
        guard version == "draft" else {
            throw ApiError(status: 409, code: "stale_terms", message: "these are not the current terms")
        }
        accepted = true
        return try await me()
    }

    func deletePost(postId: String) async throws {
        // As the API: only the author may.
        guard postId == "p2" || postId == "p4" else {
            throw ApiError(status: 403, code: "not_yours", message: "This is not your post.")
        }
        deleted.insert(postId)
    }

    func report(_ report: Report) async throws {
        reports.append(report)
    }
}
