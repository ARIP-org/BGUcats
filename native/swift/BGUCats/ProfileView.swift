import SwiftUI

/// Profile (the web app's `Profile` in web/social/home.js, and its words):
/// who is signed in, the display name and the username changed in their
/// rows, the counters, My posts, App info, Sign out, and Delete account
/// last. The system's own `List`, fields and alerts.
struct ProfileView: View {
    let world: World
    @ObservedObject var session: Session
    let me: Me
    @StateObject private var model: ProfileModel

    /// What the fields hold while they are typed in.
    @State private var name: String
    @State private var username: String
    @FocusState private var focus: ProfileModel.Field?
    /// The field whose change is on its way: "done" and leaving the field
    /// both commit, and only the first one sends.
    @State private var sending: ProfileModel.Field?
    /// The username the server last refused: leaving the field with it
    /// still typed does not ask again (it counts against ten a day).
    @State private var refusedUsername: String?
    /// The confirmation before the account goes.
    @State private var deleteAsked = false

    init(world: World, session: Session, me: Me) {
        self.world = world
        self.session = session
        self.me = me
        _model = StateObject(wrappedValue: ProfileModel(world: world, session: session))
        _name = State(initialValue: me.displayName)
        _username = State(initialValue: me.username ?? "")
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        AvatarView(
                            person: Person(userId: me.userId, username: me.username, displayName: me.displayName, avatar: me.avatar),
                            photos: world.photos,
                            size: 56
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(me.displayName)
                                .font(.headline)
                            if let username = me.username {
                                Text("@\(username)")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("profile.me")
                    LabeledContent("Cats met", value: "\(me.catsMet)")
                    LabeledContent("Encounters", value: "\(me.encounters)")
                }

                Section(ProfileWords.account) {
                    nameRow
                    usernameRow
                }

                Section {
                    NavigationLink {
                        MyPostsView(world: world, session: session)
                    } label: {
                        Label(ProfileWords.myPosts, systemImage: "square.grid.2x2")
                    }
                    .accessibilityIdentifier("row.my-posts")
                    NavigationLink {
                        AppInfoView(world: world)
                    } label: {
                        Label("App info", systemImage: "info.circle")
                    }
                    .accessibilityIdentifier("row.app-info")
                }

                Section {
                    Button("Sign out", role: .destructive) {
                        session.signOut()
                    }
                    .accessibilityIdentifier("profile.sign-out")
                }

                Section {
                    Button(role: .destructive) {
                        world.trail.mark("account: delete asked")
                        deleteAsked = true
                    } label: {
                        HStack {
                            Text(ProfileWords.deleteAccount)
                            if model.deleting {
                                Spacer()
                                ProgressView()
                            }
                        }
                    }
                    .disabled(model.deleting)
                    .accessibilityIdentifier("profile.delete-account")
                }
            }
            .navigationTitle("Profile")
            // The system's confirmation, with the plan's sentence (D14).
            // Deleting asks no terms: the API needs none for it.
            .alert(ProfileWords.deleteTitle, isPresented: $deleteAsked) {
                Button(ProfileWords.deleteAccount, role: .destructive) {
                    Task { await model.deleteAccount() }
                }
                Button("Cancel", role: .cancel) {
                    world.trail.mark("account: delete cancelled")
                }
            } message: {
                Text(ProfileWords.deleteBody)
            }
            .alert("That did not work", isPresented: noteShown) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.note ?? "")
            }
        }
        // The account as the server answered: the fields follow, but never
        // under a finger that is typing in one.
        .onChange(of: me) { _, now in
            if focus != .name {
                name = now.displayName
            }
            if focus != .username && model.usernameNote == nil {
                username = now.username ?? ""
            }
        }
        .onChange(of: focus) { left, _ in
            if let left {
                commit(left)
            }
        }
    }

    /// The display name, typed in place; under it, while the new one waits
    /// to be checked, the web app's sentence, or why it was refused.
    private var nameRow: some View {
        VStack(alignment: .leading, spacing: 6) {
            LabeledContent(ProfileWords.name) {
                TextField(ProfileWords.namePlaceholder, text: $name)
                    .multilineTextAlignment(.trailing)
                    .textContentType(.nickname)
                    .textInputAutocapitalization(.words)
                    .submitLabel(.done)
                    .focused($focus, equals: .name)
                    .onSubmit { commit(.name) }
                    .onChange(of: name) { _, now in
                        if now.count > ProfileModel.nameLimit {
                            name = String(now.prefix(ProfileModel.nameLimit))
                        }
                    }
                    .accessibilityLabel(ProfileWords.nameLabel)
                    .accessibilityIdentifier("profile.name")
            }
            if let note = model.nameNote {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("profile.name-note")
            } else if me.namePending {
                Text(ProfileWords.nameChecking)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("profile.name-pending")
            }
        }
    }

    /// The username, typed in place; under it, why it was refused, in the
    /// web app's words, with the field keeping what was typed.
    private var usernameRow: some View {
        VStack(alignment: .leading, spacing: 6) {
            LabeledContent(ProfileWords.username) {
                TextField(ProfileWords.username, text: $username)
                    .multilineTextAlignment(.trailing)
                    .textContentType(.username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .focused($focus, equals: .username)
                    .onSubmit { commit(.username) }
                    .onChange(of: username) { _, now in
                        if now.count > ProfileModel.usernameLimit {
                            username = String(now.prefix(ProfileModel.usernameLimit))
                        }
                    }
                    .accessibilityIdentifier("profile.username")
            }
            if let note = model.usernameNote {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("profile.username-note")
            } else if model.usernameSaved {
                Text(ProfileWords.usernameSaved)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("profile.username-saved")
            }
        }
    }

    /// A field is done with: its text cleaned as the web app's `TextRow`
    /// does, and sent if it changed. Nothing typed, or the same again,
    /// puts back what the account says. A name refused does too; a
    /// username refused stays as typed, under its reason.
    private func commit(_ field: ProfileModel.Field) {
        guard sending == nil else { return }
        let typed = ProfileModel.clean(field == .name ? name : username)
        let now = field == .name ? me.displayName : (me.username ?? "")
        guard !typed.isEmpty, typed != now else {
            if field == .name {
                name = now
                model.nameNote = nil
            } else {
                username = now
                model.usernameNote = nil
            }
            return
        }
        if field == .username && typed == refusedUsername {
            return
        }
        sending = field
        Task {
            let saved = await model.save(field, typed)
            sending = nil
            if field == .name && !saved {
                // Refused, or the terms declined: as it was before.
                name = session.me?.displayName ?? now
            }
            if field == .username {
                refusedUsername = saved || model.usernameNote == nil ? nil : typed
            }
        }
    }

    private var noteShown: Binding<Bool> {
        Binding(get: { model.note != nil }, set: { shown in
            if !shown {
                model.note = nil
            }
        })
    }
}

/// The web app's words for the profile (web/i18n/en.json), and the plan's
/// for deleting an account (docs/app-plan/DECISIONS.md, D14), which the
/// web app does not have yet. A Linux test holds them to both.
enum ProfileWords {
    static let account = "Account"
    static let name = "Name"
    static let nameLabel = "Display name"
    static let namePlaceholder = "Your name"
    static let nameChecking = "Others see your new name once it has been checked."
    static let nameLimit = "That's enough name changes for today. Try again tomorrow."
    static let username = "Username"
    static let usernameSaved = "Username saved"
    static let usernameTaken = "That username is taken. Try another."
    static let usernameRule = "A username is 3 to 20 letters a-z, digits, dots or underscores."
    static let usernameLimit = "That's enough username changes for today. Try again tomorrow."
    static let myPosts = "My posts"
    static let deleteAccount = "Delete account"
    static let deleteTitle = "Delete your account?"
    static let deleteBody = "Your posts, badges, points and friends will be removed for good. The cat photos you took stay with the cats' records, with nothing left that points to you."
}

/// What the profile sends, and what it says when the server refuses.
@MainActor
final class ProfileModel: ObservableObject {
    enum Field: String {
        case name, username
    }

    /// The server's limits (`NAME_MAX` in src/app/handler.py, and the
    /// username's rule), as the web app's fields hold them.
    static let nameLimit = 30
    static let usernameLimit = 20

    /// Why the last name or username was refused, in the web app's words.
    @Published var nameNote: String?
    @Published var usernameNote: String?
    @Published private(set) var usernameSaved = false
    /// Something else that failed (deleting the account), in words.
    @Published var note: String?
    @Published private(set) var deleting = false

    private let world: World
    private let session: Session

    init(world: World, session: Session) {
        self.world = world
        self.session = session
    }

    /// Runs of spaces as one, none at either end (`TextRow` in the web app).
    static func clean(_ typed: String) -> String {
        typed.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    /// Sends a new name or username, the terms first, as every write: a
    /// "no" sends nothing. True when the server took it; the account it
    /// answers is the session's at once.
    func save(_ field: Field, _ typed: String) async -> Bool {
        setNote(field, nil)
        usernameSaved = false
        // `changed`: refused for the terms although the account said they
        // were accepted; the account is read again and the person asked.
        var changed = false
        while true {
            do {
                guard try await session.termsFirst(changed: changed) else { return false }
            } catch {
                if FeedModel.signInEnded(error) { return false }
                setNote(field, (error as? ApiError)?.message ?? "Try again.")
                return false
            }
            do {
                let now: Me
                if field == .name {
                    now = try await world.backend.rename(typed)
                } else {
                    now = try await world.backend.chooseUsername(typed)
                }
                session.update(now)
                world.trail.mark("profile: \(field.rawValue) saved")
                usernameSaved = field == .username
                return true
            } catch {
                let refusal = error as? ApiError
                let why = refusal?.code ?? refusal.map { "\($0.status)" } ?? "no answer"
                world.trail.mark("profile: \(field.rawValue) refused (\(why))")
                if FeedModel.signInEnded(error) { return false }
                if refusal?.code == "terms_required" && !changed {
                    changed = true
                    continue
                }
                setNote(field, ProfileModel.words(field, refusal))
                return false
            }
        }
    }

    /// A refusal in the web app's words (`said` in its `Profile`), never
    /// its code; any other, the server's own sentence.
    static func words(_ field: Field, _ refusal: ApiError?) -> String {
        switch refusal?.code ?? "" {
        case "rate_limited": field == .name ? ProfileWords.nameLimit : ProfileWords.usernameLimit
        case "name_taken": ProfileWords.usernameTaken
        case "bad_username": ProfileWords.usernameRule
        default: refusal?.message ?? "Try again."
        }
    }

    private func setNote(_ field: Field, _ words: String?) {
        switch field {
        case .name: nameNote = words
        case .username: usernameNote = words
        }
    }

    /// "Delete account", confirmed. On success the session ends and the
    /// sign-in screen says why; a refusal is said here.
    func deleteAccount() async {
        guard !deleting else { return }
        deleting = true
        defer { deleting = false }
        do {
            try await session.deleteAccount()
        } catch {
            let status = (error as? ApiError)?.status ?? 0
            world.trail.mark("account: delete refused (\(status))")
            if FeedModel.signInEnded(error) { return }
            note = (error as? ApiError)?.message ?? "Try again."
        }
    }
}
