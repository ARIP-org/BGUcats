import Foundation

/// What the member API answers with (docs/app-plan/04-api.md), as the
/// screens use it. Read by hand from the JSON, field by field, so one
/// field a server adds or leaves out never empties a whole screen.

struct Me: Equatable {
    let userId: String
    let username: String?
    let displayName: String
    let avatar: URL?
    let role: String
    let catsMet: Int
    let encounters: Int
    /// The terms are not accepted yet: every write will be refused.
    let termsRequired: Bool
    /// The version of the terms in force (`terms.current`): what accepting
    /// them sends.
    let termsCurrent: String?
}

struct Person: Equatable {
    let userId: String
    let username: String?
    let displayName: String
    let avatar: URL?
}

struct Photo: Equatable, Identifiable {
    let id: String
    let thumb: URL?
    let medium: URL?
}

struct Post: Equatable, Identifiable {
    let id: String
    let author: Person
    let catName: String?
    let photos: [Photo]
    let text: String
    var likes: Int
    var liked: Bool
    let createdAt: Date?
    let mine: Bool
    /// Its author alone is told: "pending" while it is being checked.
    let state: String?
}

/// A campus cat as `GET /cats` lists it: what "Which cat?" shows.
struct Cat: Equatable, Identifiable {
    let id: String
    /// Nil while it has none.
    let name: String?
    let cover: URL?
}

/// What a new-cat proposal is chosen from (`POST /proposals`): the server's
/// fixed lists (src/common/proposals.py) and the campus places
/// (web/regions.json), each with the web app's words (web/i18n/en.json).
/// A copy, held equal to those files by tests/native/test_swift_app.py.
enum Campus {
    struct Choice: Identifiable, Equatable {
        let id: String
        let name: String
    }

    static let coats = [
        Choice(id: "ginger", name: "Ginger"),
        Choice(id: "black", name: "Black"),
        Choice(id: "white", name: "White"),
        Choice(id: "gray", name: "Gray"),
        Choice(id: "tabby", name: "Tabby"),
        Choice(id: "calico", name: "Calico"),
        Choice(id: "tuxedo", name: "Tuxedo"),
    ]

    static let traits = [
        Choice(id: "friendly", name: "Friendly"),
        Choice(id: "shy", name: "Shy"),
        Choice(id: "ear-tipped", name: "Ear-tipped"),
        Choice(id: "kitten", name: "Kitten"),
        Choice(id: "collar", name: "Has a collar"),
    ]

    /// "Where does it hang out?": the places, then "Somewhere else".
    static let places = [
        Choice(id: "engineering", name: "Building 96 · Engineering"),
        Choice(id: "library", name: "Aranne Library"),
        Choice(id: "union", name: "Student Union"),
        Choice(id: "dorms", name: "Dorms"),
        Choice(id: "lawn", name: "Sports lawn"),
    ]
    static let elsewhere = Choice(id: "elsewhere", name: "Somewhere else")
}

struct FeedPage {
    let posts: [Post]
    /// Absent on the last page.
    let cursor: String?
}

enum Read {
    static func url(_ any: Any?) -> URL? {
        guard let text = any as? String, !text.isEmpty else { return nil }
        return URL(string: text)
    }

    static func int(_ any: Any?) -> Int {
        (any as? NSNumber)?.intValue ?? 0
    }

    static func text(_ any: Any?) -> String? {
        guard let text = any as? String, !text.isEmpty else { return nil }
        return text
    }

    /// The API writes "2026-11-23T15:13:48.123456Z". The system's reader
    /// refuses six digits of fraction, so the fraction is dropped first.
    static func date(_ any: Any?) -> Date? {
        guard let text = any as? String else { return nil }
        let plain = text.replacingOccurrences(of: "\\.[0-9]+", with: "", options: .regularExpression)
        let reader = ISO8601DateFormatter()
        reader.formatOptions = [.withInternetDateTime]
        return reader.date(from: plain)
    }

    static func me(_ json: [String: Any]) -> Me? {
        guard let userId = json["userId"] as? String else { return nil }
        let counters = (json["counters"] as? [String: Any])?["all"] as? [String: Any]
        let terms = json["terms"] as? [String: Any]
        return Me(
            userId: userId,
            username: text(json["username"]),
            displayName: text(json["displayName"]) ?? "",
            avatar: url(json["avatar"]),
            role: text(json["role"]) ?? "user",
            catsMet: int(counters?["catsMet"]),
            encounters: int(counters?["encounters"]),
            termsRequired: (terms?["required"] as? Bool) ?? false,
            termsCurrent: text(terms?["current"])
        )
    }

    static func person(_ json: [String: Any]?) -> Person {
        Person(
            userId: (json?["userId"] as? String) ?? "",
            username: text(json?["username"]),
            displayName: text(json?["displayName"]) ?? "",
            avatar: url(json?["avatar"])
        )
    }

    /// A post's card. A card of another kind (friends' votes on a name,
    /// which this app does not draw yet) is nil.
    static func post(_ json: [String: Any]) -> Post? {
        guard let postId = json["postId"] as? String else { return nil }
        let photos = (json["photos"] as? [[String: Any]] ?? []).enumerated().map { index, photo in
            Photo(
                id: (photo["photoId"] as? String) ?? "\(postId)-\(index)",
                thumb: url(photo["thumb"]),
                medium: url(photo["medium"])
            )
        }
        return Post(
            id: postId,
            author: person(json["author"] as? [String: Any]),
            catName: text((json["cat"] as? [String: Any])?["name"]),
            photos: photos,
            text: (json["text"] as? String) ?? "",
            likes: int(json["likes"]),
            liked: (json["liked"] as? Bool) ?? false,
            createdAt: date(json["createdAt"]),
            mine: (json["mine"] as? Bool) ?? false,
            state: text(json["state"])
        )
    }

    /// `GET /cats`: every public cat, in the server's order. One with no id
    /// is left out; one with no name or no photo is kept.
    static func cats(_ json: [String: Any]) -> [Cat] {
        (json["cats"] as? [[String: Any]] ?? []).compactMap { cat in
            guard let catId = text(cat["catId"]) else { return nil }
            let cover = cat["cover"] as? [String: Any]
            return Cat(id: catId, name: text(cat["name"]), cover: url(cover?["thumb"]) ?? url(cover?["medium"]))
        }
    }

    static func page(_ json: [String: Any]) -> FeedPage {
        let cards = json["cards"] as? [[String: Any]] ?? []
        return FeedPage(posts: cards.compactMap(post), cursor: text(json["cursor"]))
    }
}
