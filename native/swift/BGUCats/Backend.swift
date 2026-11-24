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

    /// One call. `name` is what the trail calls it: the kind of call, never
    /// its address, which can carry an id.
    private func call(_ method: String, _ path: String, cursor: String? = nil, body payload: [String: Any]? = nil, as name: String) async throws -> [String: Any] {
        let token: String
        switch await auth.pass() {
        case .token(let fresh):
            token = fresh
        case .signedOut:
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        case .notNow:
            throw ApiError(status: 0, code: nil, message: "The server could not be reached. Check the connection and try again.")
        }
        var address = Site.origin.absoluteString + "/api/v1" + path
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
        if let payload {
            request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
            request.setValue("application/json", forHTTPHeaderField: "content-type")
        }

        let began = Date()
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            trail.mark("api: \(name) not reached (\(Auth.kind(error)))")
            throw ApiError(status: 0, code: nil, message: "The server could not be reached. Check the connection and try again.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        trail.mark("api: \(name) \(status) in \(Int(Date().timeIntervalSince(began) * 1000)) ms")

        let body = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
        if status == 401 {
            // The server no longer takes this token. The tabs must not
            // stay up over calls that can only fail: the session is told.
            auth.ended("the API answered 401")
            throw ApiError(status: 401, code: "signed_out", message: "Your sign-in ended. Sign in again.")
        }
        guard (200..<300).contains(status) else {
            throw ApiError(
                status: status,
                code: body["code"] as? String,
                message: (body["error"] as? String) ?? "The request failed (\(status))."
            )
        }
        return body
    }
}

/// For UI tests: a made-up member and three made-up posts, the same every
/// time. No network.
final class StandInBackend: Backend {
    private let start: Date
    private let gate: StandInGate
    /// The test asked for a sign-in that ends at the first like.
    private let ends: Bool
    private var liked: Set<String> = []
    /// The made-up member has accepted the terms ("-termsRequired": not).
    private var accepted: Bool
    /// "-termsChanged": the terms changed after the account was read, so
    /// the first `me()` says nothing is required and the first like is
    /// refused all the same.
    private var stale: Bool

    init(start: Date, gate: StandInGate, ends: Bool = false, termsRequired: Bool = false, termsChanged: Bool = false) {
        self.start = start
        self.gate = gate
        self.ends = ends
        self.accepted = !(termsRequired || termsChanged)
        self.stale = termsChanged
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
            termsRequired: !accepted && !stale,
            termsCurrent: "draft"
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
        return FeedPage(posts: posts, cursor: nil)
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
}
