import Foundation

/// An id made on the phone, the way `ulid` in `web/outbox.js` and the API make and expect
/// one (docs/app-plan/04-api.md, "Ids from the phone"): 26 characters of
/// Crockford's base 32, the time in milliseconds first (10 characters),
/// then 80 random bits (16). Made once per thing, so sending it again is
/// the same request.
enum Ulid {
    static let alphabet = Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    static func make(at now: Date = Date()) -> String {
        var time = UInt64(max(0, now.timeIntervalSince1970 * 1000))
        var head: [Character] = []
        for _ in 0..<10 {
            head.append(alphabet[Int(time % 32)])
            time /= 32
        }
        var tail = ""
        for _ in 0..<16 {
            tail.append(alphabet[Int.random(in: 0..<32)])
        }
        return String(head.reversed()) + tail
    }
}
