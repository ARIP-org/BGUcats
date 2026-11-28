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
    /// A new display name is waiting to be checked: its owner sees it
    /// already (`displayName`), everyone else once it has been.
    var namePending: Bool = false
    /// The same for a new profile photo: `avatar` is already the new one
    /// for its owner, everyone else sees it once it has been checked.
    var avatarPending: Bool = false
}

struct Person: Hashable, Identifiable {
    let userId: String
    let username: String?
    let displayName: String
    let avatar: URL?

    var id: String { userId }

    /// The name a screen shows: the display name, or the username when
    /// there is none (`displayName || username` in the web app).
    var shownName: String {
        displayName.isEmpty ? (username ?? "") : displayName
    }
}

/// `GET /friends?period=…`: whose cats are counted, this month (an Israel
/// month) or in all.
enum FriendsPeriod: String {
    case month, all
}

/// One person of `GET /friends`: the member (`me`) or one of their
/// friends, with how many cats they found in the period. The server sends
/// them most found first, so the podium is the first three.
struct Friend: Equatable, Identifiable {
    let person: Person
    let found: Int
    let me: Bool

    var id: String { person.userId }
}

/// `GET /users/{userId}`: a person as others see them.
struct PersonDetail: Equatable {
    let person: Person
    /// Cats found, in all.
    let found: Int
    let me: Bool
    /// They and the member are friends (`friend == "yes"`), and since when.
    var friend: Bool
    var friendSince: Date?
    /// How many friends the two have in common, never who; nil on one's
    /// own page.
    let mutual: Int?
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
    /// Its author alone is told: "pending" while it is being checked,
    /// "hidden" when others cannot see it, "visible" when they can.
    let state: String?
    /// Its author alone is told: it names a new cat an admin has not
    /// confirmed yet (the proposal is still open), so nobody else sees it.
    var heldForNewCat: Bool = false

    /// Its state in the web app's words (`post.state.*`,
    /// `post.waitingNewCat`), when it is not simply public; nil when it is.
    var stateWords: String? {
        if heldForNewCat {
            return "Waiting for an admin to confirm the new cat"
        }
        switch state {
        case "pending": return "Being checked"
        case "hidden": return "Not published"
        case "removed": return "Removed"
        default: return nil
        }
    }
}

/// A campus cat as `GET /cats` lists it. "Which cat?" reads the first
/// three; the gallery and a cat's page the rest. A field the server left
/// out (or sent as null) is nil here, and a screen leaves it out: never a
/// zero or a dash the server did not send.
struct Cat: Equatable, Identifiable {
    let id: String
    /// Nil while it has none.
    let name: String?
    /// The small picture: what a list shows.
    let cover: URL?
    /// The larger one, for the cat of the day.
    var coverMedium: URL? = nil
    /// Where the shown name came from: `poll`, `admin` or `none`.
    var nameSource: String? = nil
    /// A campus place's id (`Campus.places`).
    var regionId: String? = nil
    /// A coat's id (`Campus.coats`).
    var coat: String? = nil
    /// One decimal, 4.0 for the most popular cat. Nil: none sent (nobody
    /// met it lately, or the `gpa` flag is off).
    var gpa: Double? = nil
    var posts: Int? = nil
    var likes: Int? = nil
    var lastSeenAt: Date? = nil
    var firstSeenAt: Date? = nil

    /// The web app's words for a cat with no name yet (`cat.noName`).
    static let noName = "A cat with no name yet"

    var shownName: String { name ?? Cat.noName }

    /// Its usual place in the web app's words, if it is a campus place.
    var area: String? {
        regionId.flatMap { id in Campus.places.first { $0.id == id }?.name }
    }

    var coatName: String? {
        coat.flatMap { id in Campus.coats.first { $0.id == id }?.name }
    }

    /// The name poll's summary, as words (`cat.namedBy…` in the web app).
    var named: String? {
        Cat.named(by: nameSource)
    }

    /// The words for where a name came from; nil for a source with none.
    static func named(by source: String?) -> String? {
        switch source {
        case "poll": "Named by vote"
        case "admin": "Named by the people who look after the cats"
        case "none": "No name yet"
        default: nil
        }
    }
}

/// `GET /cats`: every public cat, and today's cat of the day (the same
/// for everyone on one Israel day; nil when there is none).
struct CatList: Equatable {
    let cats: [Cat]
    let catOfTheDay: String?
}

/// The caller and one cat (`met` on `GET /cats/{catId}`).
struct Met: Equatable {
    let encounters: Int
    let days: Int
    /// "2026-11-03": the Israel day of the first and of the last.
    let firstDay: Date?
    let lastDay: Date?
}

/// `GET /cats/{catId}`: the cat as the list has it, and more.
struct CatDetail: Equatable {
    let cat: Cat
    /// Nil when it has none.
    let bio: String?
    /// Nil: the caller never met this cat.
    let met: Met?
    /// Newest first.
    let photos: [Photo]
}

/// The name poll as `GET /cats/{catId}/names` answers it, and every write
/// to it (`POST …/names`, `PUT` and `DELETE …/vote`) too: the poll as it
/// is now, which the page draws, never a guess of its own.
struct Poll: Equatable {
    struct Option: Equatable, Identifiable {
        let nameKey: String
        let name: String
        let votes: Int
        /// The option that names the cat (`polls.leader` on the server).
        let leading: Bool
        /// The caller's vote is on it.
        let mine: Bool
        /// The caller's own suggestion, still being checked; nobody else
        /// sees it.
        let pending: Bool

        var id: String { nameKey }
    }

    /// The name the cat goes by now, and why (`poll`, `admin`, `locked`,
    /// `none`), as these options make it. Nil when not sent.
    let name: String?
    let nameSource: String?
    /// Live options most votes first, then the caller's pending ones.
    let options: [Option]
    /// Votes on live options. Nil when not sent.
    let total: Int?
    /// The name an admin set; the poll goes on below it.
    let locked: String?
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
            termsCurrent: text(terms?["current"]),
            namePending: (json["namePending"] as? Bool) ?? false,
            avatarPending: (json["avatarPending"] as? Bool) ?? false
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
            state: text(json["state"]),
            heldForNewCat: text((json["proposal"] as? [String: Any])?["status"]) == "open"
        )
    }

    /// A number the server sent, or nil when it sent none (or null).
    static func number(_ any: Any?) -> Int? {
        (any as? NSNumber)?.intValue
    }

    /// A day as the API writes it, "2026-11-03".
    static func day(_ any: Any?) -> Date? {
        guard let text = any as? String else { return nil }
        let reader = DateFormatter()
        reader.locale = Locale(identifier: "en_US_POSIX")
        reader.timeZone = TimeZone(identifier: "UTC")
        reader.dateFormat = "yyyy-MM-dd"
        return reader.date(from: text)
    }

    /// One cat of `GET /cats` or `GET /cats/{catId}`. One with no id is
    /// nil; one with no name or no photo is kept.
    static func cat(_ json: [String: Any]) -> Cat? {
        guard let catId = text(json["catId"]) else { return nil }
        let cover = json["cover"] as? [String: Any]
        return Cat(
            id: catId,
            name: text(json["name"]),
            cover: url(cover?["thumb"]) ?? url(cover?["medium"]),
            coverMedium: url(cover?["medium"]) ?? url(cover?["thumb"]),
            nameSource: text(json["nameSource"]),
            regionId: text(json["regionId"]),
            coat: text(json["coat"]),
            gpa: (json["gpa"] as? NSNumber)?.doubleValue,
            posts: number(json["posts"]),
            likes: number(json["likes"]),
            lastSeenAt: date(json["lastSeenAt"]),
            firstSeenAt: date(json["firstSeenAt"])
        )
    }

    /// `GET /cats`: every public cat, in the server's order.
    static func cats(_ json: [String: Any]) -> [Cat] {
        (json["cats"] as? [[String: Any]] ?? []).compactMap { Read.cat($0) }
    }

    /// `GET /cats` whole: the cats and the cat of the day, which is left
    /// out if it is not one of them.
    static func catList(_ json: [String: Any]) -> CatList {
        let listed = Read.cats(json)
        let today = text(json["catOfTheDay"])
        return CatList(cats: listed, catOfTheDay: listed.contains { $0.id == today } ? today : nil)
    }

    /// `GET /cats/{catId}`.
    static func catDetail(_ json: [String: Any]) -> CatDetail? {
        guard let body = json["cat"] as? [String: Any], let read = Read.cat(body) else { return nil }
        let met = (body["met"] as? [String: Any]).map { met in
            Met(
                encounters: int(met["encounters"]),
                days: int(met["days"]),
                firstDay: day(met["firstDay"]),
                lastDay: day(met["lastDay"])
            )
        }
        let photos = (body["photos"] as? [[String: Any]] ?? []).enumerated().map { index, photo in
            Photo(
                id: (photo["photoId"] as? String) ?? "\(read.id)-\(index)",
                thumb: url(photo["thumb"]),
                medium: url(photo["medium"])
            )
        }
        return CatDetail(cat: read, bio: text(body["bio"]), met: met, photos: photos)
    }

    /// The name poll (`_names_view` in src/app/handler.py). An option with
    /// no key or no name is skipped; an answer with no options at all is
    /// not a poll.
    static func poll(_ json: [String: Any]) -> Poll? {
        guard let options = json["options"] as? [[String: Any]] else { return nil }
        return Poll(
            name: text(json["name"]),
            nameSource: text(json["nameSource"]),
            options: options.compactMap { option in
                guard let key = text(option["nameKey"]), let name = text(option["name"]) else { return nil }
                return Poll.Option(
                    nameKey: key,
                    name: name,
                    votes: int(option["votes"]),
                    leading: (option["leading"] as? Bool) ?? false,
                    mine: (option["mine"] as? Bool) ?? false,
                    pending: (option["pending"] as? Bool) ?? false
                )
            },
            total: number(json["total"]),
            locked: text(json["locked"])
        )
    }

    /// `GET /friends`: the people in the server's order. One with no id is
    /// skipped.
    static func friends(_ json: [String: Any]) -> [Friend] {
        (json["people"] as? [[String: Any]] ?? []).compactMap { row in
            guard text(row["userId"]) != nil else { return nil }
            return Friend(person: person(row), found: int(row["found"]), me: (row["me"] as? Bool) ?? false)
        }
    }

    /// `GET /users/{userId}`.
    static func personDetail(_ json: [String: Any]) -> PersonDetail? {
        guard let body = json["person"] as? [String: Any], text(body["userId"]) != nil else { return nil }
        return PersonDetail(
            person: person(body),
            found: int(body["found"]),
            me: (body["me"] as? Bool) ?? false,
            friend: text(body["friend"]) == "yes",
            friendSince: date(body["friendSince"]),
            mutual: number(body["mutual"])
        )
    }

    static func page(_ json: [String: Any]) -> FeedPage {
        let cards = json["cards"] as? [[String: Any]] ?? []
        return FeedPage(posts: cards.compactMap(post), cursor: text(json["cursor"]))
    }
}
