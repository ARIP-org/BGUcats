import Foundation

/// The app's own account of what it was doing, kept on this phone: the last
/// eighty lines, as in the web app (web/app.html). A line says what
/// happened, never who: no name, no address, no token, nothing anyone
/// wrote. "App info" shows it, and a bug on someone's phone is asked for
/// with "copy App info", not guessed at.
final class Trail {
    static let limit = 80
    static let lineLimit = 200
    static let key = "bgucats.trail"

    private let store: TrailStore
    private let now: () -> Date
    private let lock = NSLock()

    init(store: TrailStore = UserDefaults.standard, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.now = now
    }

    /// Keeps one line. Never throws and never blocks for long: a line not
    /// kept is never a reason to stop.
    func mark(_ what: String) {
        lock.lock()
        defer { lock.unlock() }
        var kept = store.lines(Trail.key)
        kept.append("\(Trail.stamp(now())) \(what.prefix(Trail.lineLimit))")
        if kept.count > Trail.limit {
            kept.removeFirst(kept.count - Trail.limit)
        }
        store.keep(kept, Trail.key)
    }

    var lines: [String] {
        lock.lock()
        defer { lock.unlock() }
        return store.lines(Trail.key)
    }

    /// Month, day and time to the millisecond, in the phone's own zone:
    /// what a person compares with "it froze at about ten".
    static func stamp(_ date: Date, zone: TimeZone = .current) -> String {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = zone
        format.dateFormat = "MM-dd HH:mm:ss.SSS"
        return format.string(from: date)
    }
}

/// Where the lines are kept.
protocol TrailStore {
    func lines(_ key: String) -> [String]
    func keep(_ lines: [String], _ key: String)
}

extension UserDefaults: TrailStore {
    func lines(_ key: String) -> [String] {
        stringArray(forKey: key) ?? []
    }

    func keep(_ lines: [String], _ key: String) {
        set(lines, forKey: key)
    }
}

/// For UI tests: nothing is written to the phone.
final class MemoryStore: TrailStore {
    private var kept: [String: [String]] = [:]

    func lines(_ key: String) -> [String] {
        kept[key] ?? []
    }

    func keep(_ lines: [String], _ key: String) {
        kept[key] = lines
    }
}
