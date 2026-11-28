import PhotosUI
import SwiftUI

/// Profile (the web app's `Profile` in web/social/home.js, and its words):
/// who is signed in, with the profile photo chosen, replaced or removed
/// from a menu on it; the display name and the username changed in their
/// rows, the counters, My posts, App info, Sign out, and Delete account
/// last. The system's own `List`, fields, menu, picker and alerts.
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
    /// The other field, finished while one was on its way: it is sent
    /// when that one is answered, not dropped.
    @State private var waiting: ProfileModel.Field?
    /// The username the server last refused: leaving the field with it
    /// still typed does not ask again (it counts against ten a day).
    @State private var refusedUsername: String?
    /// The confirmation before the account goes.
    @State private var deleteAsked = false
    /// The system's photo picker is up, and what was chosen in it.
    @State private var picking = false
    @State private var picked: PhotosPickerItem?
    /// The confirmation before the photo is removed.
    @State private var removeAsked = false
    /// Under UI tests: how many drawn pictures were handed out.
    @State private var drawn = 0

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
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 14) {
                            photoMenu
                            VStack(alignment: .leading, spacing: 2) {
                                Text(me.displayName)
                                    .font(.headline)
                                if let username = me.username {
                                    Text("@\(username)")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityIdentifier("profile.me")
                        }
                        photoNotes
                    }
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

                // A section of its own, below the two rows above, so they
                // stay where the account's walk finds them.
                Section {
                    NavigationLink {
                        FriendsView(world: world, session: session)
                    } label: {
                        Label(FriendsWords.title, systemImage: "person.2")
                    }
                    .accessibilityIdentifier("row.friends")
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
            // Removing the photo asks first, with the system's alert. It
            // asks no terms: the API needs none for it.
            .alert(ProfileWords.photoRemoveTitle, isPresented: $removeAsked) {
                Button(ProfileWords.photoRemove, role: .destructive) {
                    Task { await model.removePhoto() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text(ProfileWords.photoRemoveBody)
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
        // The system's picker: images only, and it needs no permission.
        .photosPicker(isPresented: $picking, selection: $picked, matching: .images)
        .onChange(of: picked) { _, item in
            guard let item else { return }
            picked = nil
            Task {
                // Nil when the phone cannot hand the picture over (not on
                // this phone yet, or not a picture): said, nothing sent.
                let file = try? await item.loadTransferable(type: Data.self)
                await model.choosePhoto(file)
            }
        }
    }

    /// The photo at the top, and the system's menu on it: "Choose a photo",
    /// and "Remove photo" when there is one.
    private var photoMenu: some View {
        Menu {
            Section(ProfileWords.photoMenu) {
                Button {
                    choose()
                } label: {
                    Label(ProfileWords.photoChoose, systemImage: "photo.on.rectangle")
                }
                if me.avatar != nil {
                    Button(role: .destructive) {
                        removeAsked = true
                    } label: {
                        Label(ProfileWords.photoRemove, systemImage: "trash")
                    }
                }
            }
        } label: {
            AvatarView(
                person: Person(userId: me.userId, username: me.username, displayName: me.displayName, avatar: me.avatar),
                photos: world.photos,
                size: 64
            )
            .overlay {
                if model.photoBusy {
                    Circle()
                        .fill(.black.opacity(0.35))
                    ProgressView()
                        .tint(.white)
                }
            }
            .overlay(alignment: .bottomTrailing) {
                Image(systemName: "pencil.circle.fill")
                    .font(.title3)
                    .symbolRenderingMode(.palette)
                    .foregroundStyle(.white, .tint)
                    .accessibilityHidden(true)
            }
        }
        .buttonStyle(.borderless)
        .disabled(model.photoBusy)
        .accessibilityLabel(ProfileWords.photoChange)
        .accessibilityValue(photoState)
        .accessibilityIdentifier("profile.photo")
    }

    /// What the photo is, for VoiceOver and the walk.
    private var photoState: String {
        if me.avatar == nil {
            return "no photo"
        }
        return me.avatarPending ? "photo, being checked" : "photo"
    }

    /// Under the photo: while the new one waits to be checked, the web
    /// app's sentence; why the last one was refused, in its words, with
    /// "Try again" when sending it failed; or that it was removed.
    @ViewBuilder private var photoNotes: some View {
        if let note = model.photoNote {
            Text(note)
                .font(.footnote)
                .foregroundStyle(.red)
                .accessibilityIdentifier("profile.photo-note")
            if model.photoRetry {
                Button("Try again") {
                    Task { await model.sendPhoto() }
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier("profile.photo-retry")
            }
        }
        if me.avatarPending {
            Text(ProfileWords.photoChecking)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .accessibilityIdentifier("profile.photo-pending")
        } else if let said = model.photoSaid {
            Text(said)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .accessibilityIdentifier("profile.photo-said")
        }
    }

    /// "Choose a photo": the system's picker, or under UI tests (where
    /// there is none to drive) a drawn picture with made-up EXIF in it.
    private func choose() {
        if world.drawn {
            drawn += 1
            let file = DrawnPhotos.cameraFile("avatar \(drawn)")
            Task { await model.choosePhoto(file) }
        } else {
            picking = true
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
        guard sending == nil else {
            // The same field again ("done", then leaving it) sends nothing
            // more; the other one waits for the first answer.
            if sending != field {
                waiting = field
            }
            return
        }
        // The account as the server last answered: a field that waited is
        // compared with what the first change left, not with what was
        // drawn when it started.
        let account = session.me ?? me
        let typed = ProfileModel.clean(field == .name ? name : username)
        let now = field == .name ? account.displayName : (account.username ?? "")
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
            if let next = waiting {
                waiting = nil
                commit(next)
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
    static let photoChange = "Change profile photo"
    static let photoMenu = "Profile photo"
    static let photoChoose = "Choose a photo"
    static let photoRemove = "Remove photo"
    static let photoRemoved = "Photo removed"
    static let photoChecking = "Others see your new photo once it has been checked."
    static let photoLimit = "That's enough photo changes for today. Try again tomorrow."
    static let photoBad = "That picture could not be used. Try another one."
    /// The web app removes with no question; the issue asks for the
    /// system's confirmation, in these words.
    static let photoRemoveTitle = "Remove your profile photo?"
    static let photoRemoveBody = "Everyone will see your initial instead."
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
    /// The profile photo: a picture is being made ready or sent; why the
    /// last one failed, in words; whether "Try again" can send it again;
    /// and that it was removed.
    @Published private(set) var photoBusy = false
    @Published private(set) var photoNote: String?
    @Published private(set) var photoRetry = false
    @Published private(set) var photoSaid: String?
    /// The picture made ready and not yet taken by the server, for "Try
    /// again"; and where it was to go, while that may still be used.
    private var ready: Data?
    private var started: AvatarStart?

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

    /// A picture chosen (the file as the picker handed it over; nil when it
    /// could not): made ready on the phone, away from the screen's thread,
    /// then sent. One the phone cannot open says so and sends nothing.
    func choosePhoto(_ file: Data?) async {
        guard !photoBusy else { return }
        world.trail.mark("avatar: chosen")
        photoNote = nil
        photoRetry = false
        photoSaid = nil
        ready = nil
        started = nil
        photoBusy = true
        let made: Data?
        if let file {
            made = await Task.detached(priority: .userInitiated) { try? Avatar.ready(file) }.value
        } else {
            made = nil
        }
        photoBusy = false
        guard let made else {
            world.trail.mark("avatar: could not be read")
            photoNote = ProfileWords.photoBad
            return
        }
        let kb = Int((Double(made.count) / 1000).rounded())
        world.trail.mark("avatar: made ready, \(kb) KB")
        ready = made
        await sendPhoto()
    }

    /// The three calls, the terms first: where to send it, the bytes, the
    /// confirmation, whose answer is the account. Until the server has
    /// taken it the photo shown is the one from before. A refusal is said
    /// in the web app's words; a failure to reach the server or storage
    /// keeps the picture for "Try again".
    func sendPhoto() async {
        guard let jpeg = ready, !photoBusy else { return }
        photoBusy = true
        defer { photoBusy = false }
        photoNote = nil
        photoRetry = false
        // `changed`: refused for the terms although the account said they
        // were accepted; the account is read again and the person asked.
        var changed = false
        while true {
            do {
                guard try await session.termsFirst(changed: changed) else {
                    ready = nil
                    return
                }
            } catch {
                if FeedModel.signInEnded(error) { return }
                photoNote = (error as? ApiError)?.message ?? "Try again."
                photoRetry = true
                return
            }
            do {
                let target: AvatarStart
                if let kept = started {
                    target = kept
                } else {
                    target = try await world.backend.startAvatar()
                    started = target
                }
                _ = try await world.backend.uploadAvatar(jpeg, to: target.target)
                let now = try await world.backend.completeAvatar(avatarId: target.avatarId)
                session.update(now)
                ready = nil
                started = nil
                world.trail.mark("avatar: saved, being checked")
                return
            } catch {
                let refusal = error as? ApiError
                let code = refusal?.code
                if FeedModel.signInEnded(error) { return }
                if code == "terms_required" && !changed {
                    world.trail.mark("avatar: refused (terms_required)")
                    changed = true
                    continue
                }
                if code == "storage" {
                    // The upload's address may be stale: a new one next time.
                    started = nil
                }
                switch code {
                case "bad_photo", "rate_limited":
                    let why = code ?? ""
                    world.trail.mark("avatar: refused (\(why))")
                    photoNote = ProfileModel.photoWords(refusal)
                    ready = nil
                    started = nil
                default:
                    let why = (refusal?.status ?? 0) == 0 ? (code ?? "no answer") : "\(refusal?.status ?? 0)"
                    world.trail.mark("avatar: not sent (\(why))")
                    photoNote = ProfileModel.photoWords(refusal)
                    photoRetry = true
                }
                return
            }
        }
    }

    /// A refusal of the photo in the web app's words, never its code
    /// (`photoPicked` in its `Profile`); any other, the server's sentence.
    static func photoWords(_ refusal: ApiError?) -> String {
        switch refusal?.code ?? "" {
        case "bad_photo": ProfileWords.photoBad
        case "rate_limited": ProfileWords.photoLimit
        default: refusal?.message ?? "Try again."
        }
    }

    /// "Remove photo", confirmed: the account with no photo, at once.
    func removePhoto() async {
        guard !photoBusy else { return }
        photoBusy = true
        defer { photoBusy = false }
        photoNote = nil
        photoRetry = false
        photoSaid = nil
        ready = nil
        started = nil
        do {
            let now = try await world.backend.removeAvatar()
            session.update(now)
            world.trail.mark("avatar: removed")
            photoSaid = ProfileWords.photoRemoved
        } catch {
            let status = (error as? ApiError)?.status ?? 0
            world.trail.mark("avatar: remove refused (\(status))")
            if FeedModel.signInEnded(error) { return }
            photoNote = (error as? ApiError)?.message ?? "Try again."
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
