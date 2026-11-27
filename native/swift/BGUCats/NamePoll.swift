import SwiftUI

/// The web app's words for the poll (`poll.*` in web/i18n/en.json), held
/// equal to them by tests/native/test_swift_app.py.
enum PollWords {
    static let title = "Name poll"
    static let lead = "Suggest your own name or vote for the one you like."
    static let leading = "LEADING"
    static let checking = "Being checked"
    static let suggest = "Suggest a name"
    static let suggestButton = "Suggest"
    static let suggested = "Your name is in"
    static let notAccepted = "That name was not accepted."
    static let tryAgain = "The poll just changed. Try again."
    static let slowDown = "That's enough for now. Try again later."

    /// `poll.locked`.
    static func locked(_ name: String) -> String {
        "The people who look after the cats have set the name: \(name). The poll goes on."
    }

    /// `poll.votes`.
    static func votes(_ count: Int) -> String {
        count == 1 ? "1 vote" : "\(count) votes"
    }

    /// `error.generic`.
    static func generic(_ message: String) -> String {
        "Something went wrong: \(message)"
    }
}

/// The name poll on a cat's page (`GET /cats/{catId}/names`, the web app's
/// `web/social/poll.js`). Every write answers with the poll as it is now,
/// and that answer is what is drawn: nothing is counted on the phone
/// before the server has. The terms come before a vote or a suggestion;
/// taking a vote back writes nothing others read and asks nothing.
@MainActor
final class PollModel: ObservableObject {
    @Published private(set) var poll: Poll?
    /// A write is on its way: the options and Suggest wait for it.
    @Published private(set) var busy = false
    /// What went wrong, in the web app's words.
    @Published var note: String?
    /// The last suggestion went in (`poll.suggested`).
    @Published private(set) var suggested = false

    private let world: World
    private let session: Session
    private let catId: String

    init(world: World, session: Session, catId: String) {
        self.world = world
        self.session = session
        self.catId = catId
    }

    private enum Write {
        case vote(String)
        case unvote
        case suggest(String)

        /// What the trail calls it.
        var kind: String {
            switch self {
            case .vote: "vote"
            case .unvote: "vote taken back"
            case .suggest: "suggestion"
            }
        }
    }

    /// The first read, and a pull to refresh. A poll that cannot be read
    /// leaves the one on screen, or none: the page above it stands alone.
    func read() async {
        do {
            poll = try await world.backend.names(catId: catId)
        } catch {
            // A sign-in that ended is the session's to say; anything else
            // leaves the poll as it was.
        }
    }

    /// A tap on an option: the member's vote moves to it, or, on their own
    /// choice, is taken back.
    func choose(_ option: Poll.Option) async {
        _ = await send(option.mine ? .unvote : .vote(option.nameKey))
    }

    /// A name typed, cleaned as the web app does before sending. True when
    /// it went in, so the field is emptied.
    func suggest(_ typed: String) async -> Bool {
        let name = PollModel.clean(typed)
        guard !name.isEmpty else { return false }
        suggested = false
        let went = await send(.suggest(name))
        suggested = went
        return went
    }

    /// Runs of spaces as one, none at either end.
    static func clean(_ typed: String) -> String {
        typed.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    private func perform(_ write: Write) async throws -> Poll {
        switch write {
        case .vote(let key):
            return try await world.backend.vote(catId: catId, nameKey: key)
        case .unvote:
            return try await world.backend.unvote(catId: catId)
        case .suggest(let name):
            return try await world.backend.suggest(catId: catId, name: name)
        }
    }

    private func send(_ write: Write) async -> Bool {
        guard !busy else { return false }
        busy = true
        defer { busy = false }
        // `changed`: the server refused for the terms although the account
        // said they were accepted; the account is read again and the
        // person asked once more.
        var changed = false
        while true {
            if changed || !isUnvote(write) {
                do {
                    guard try await session.termsFirst(changed: changed) else { return false }
                } catch {
                    if FeedModel.signInEnded(error) { return false }
                    note = (error as? ApiError)?.message ?? "Try again."
                    return false
                }
            }
            do {
                let now = try await perform(write)
                poll = now
                world.trail.mark(PollModel.done(write, now))
                return true
            } catch {
                let refusal = error as? ApiError
                let status = refusal.map { "\($0.status)" } ?? "no answer"
                world.trail.mark("poll: \(write.kind) refused (\(status))")
                if FeedModel.signInEnded(error) { return false }
                switch refusal?.code ?? "" {
                case "terms_required" where !changed:
                    changed = true
                    continue
                case "not_accepted":
                    note = PollWords.notAccepted
                case "try_again", "gone":
                    // The poll moved under the member: what it is now, then
                    // the words.
                    await read()
                    note = PollWords.tryAgain
                case "rate_limited":
                    note = PollWords.slowDown
                default:
                    if let refusal, refusal.status != 0 {
                        note = PollWords.generic(refusal.message)
                    } else {
                        note = refusal?.message ?? "Try again."
                    }
                }
                return false
            }
        }
    }

    private func isUnvote(_ write: Write) -> Bool {
        if case .unvote = write { return true }
        return false
    }

    /// The trail's line for a write that went, with what the answer says
    /// of it: never the name, its key or the cat.
    private static func done(_ write: Write, _ poll: Poll) -> String {
        switch write {
        case .vote:
            return "poll: voted"
        case .unvote:
            return "poll: vote taken back"
        case .suggest:
            let chosen = poll.options.first { $0.mine }
            let state = chosen == nil ? "not in the poll" : chosen?.pending == true ? "being checked" : "merged"
            return "poll: suggested, \(state)"
        }
    }
}

/// The poll as the page draws it: the count, the lead or the locked name,
/// the options as rows (the leader marked, the member's choice checked,
/// their own name "Being checked"), and a field with Suggest.
struct NamePollSection: View {
    @ObservedObject var model: PollModel
    @State private var typed = ""
    @FocusState private var typing: Bool

    var body: some View {
        if let poll = model.poll {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text(PollWords.title)
                        .font(.headline)
                    Spacer()
                    if let total = poll.total {
                        Text(PollWords.votes(total))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .accessibilityIdentifier("poll.total")
                    }
                }
                if let locked = poll.locked {
                    Text(PollWords.locked(locked))
                        .font(.subheadline)
                        .accessibilityIdentifier("poll.locked")
                } else {
                    Text(PollWords.lead)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                if !poll.options.isEmpty {
                    GroupBox {
                        VStack(spacing: 0) {
                            ForEach(Array(poll.options.enumerated()), id: \.element.id) { index, option in
                                if index > 0 {
                                    Divider()
                                }
                                PollRow(option: option) {
                                    Task { await model.choose(option) }
                                }
                                .disabled(model.busy)
                            }
                        }
                    }
                }

                HStack(spacing: 10) {
                    TextField(PollWords.suggest, text: $typed)
                        .textFieldStyle(.roundedBorder)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .submitLabel(.done)
                        .focused($typing)
                        .onSubmit(send)
                        .onChange(of: typed) { _, now in
                            let cut = ScanFlow.cut(now, to: ScanFlow.nameLimit)
                            if cut != now {
                                typed = cut
                            }
                        }
                        .accessibilityIdentifier("poll.field")
                    Button(PollWords.suggestButton, action: send)
                        .buttonStyle(.bordered)
                        .disabled(model.busy || PollModel.clean(typed).isEmpty)
                        .accessibilityIdentifier("poll.suggest")
                }
                if model.suggested {
                    Label(PollWords.suggested, systemImage: "checkmark.circle")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("poll.suggested")
                }
            }
            .padding(.horizontal)
            .alert("That did not work", isPresented: Binding(get: { model.note != nil }, set: { if !$0 { model.note = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.note ?? "")
            }
        }
    }

    private func send() {
        let name = typed
        typing = false
        Task {
            if await model.suggest(name) {
                typed = ""
            }
        }
    }
}

/// One option: a check for the member's choice, the name, its marks, and
/// its votes. A tap votes for it, or takes the vote back.
private struct PollRow: View {
    let option: Poll.Option
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            HStack(spacing: 12) {
                Image(systemName: option.mine ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(option.mine ? AnyShapeStyle(TintShapeStyle()) : AnyShapeStyle(HierarchicalShapeStyle.secondary))
                    .imageScale(.large)
                VStack(alignment: .leading, spacing: 2) {
                    Text(option.name)
                        .fontWeight(option.leading ? .semibold : .regular)
                    if option.pending {
                        Text(PollWords.checking)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if option.leading {
                    Text(PollWords.leading)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.tint)
                }
                Text("\(option.votes)")
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 10)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityValue(option.mine ? "chosen" : "not chosen")
        .accessibilityAddTraits(option.mine ? .isSelected : [])
        .accessibilityIdentifier("poll.option.\(option.nameKey)")
    }

    private var label: String {
        var parts = [option.name, PollWords.votes(option.votes)]
        if option.leading {
            parts.append(PollWords.leading)
        }
        if option.pending {
            parts.append(PollWords.checking)
        }
        return parts.joined(separator: ", ")
    }
}
