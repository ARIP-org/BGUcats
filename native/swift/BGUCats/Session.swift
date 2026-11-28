import SwiftUI

/// Who is using the app, and whether it has started: what the first
/// screen is decided by.
@MainActor
final class Session: ObservableObject {
    enum Phase {
        /// The account is being read.
        case starting
        /// Nobody is signed in; `note` says why the last sign-in ended.
        case signedOut(note: String?)
        case signedIn(Me)
        /// Signed in, and the account could not be read.
        case failed(String)
    }

    @Published private(set) var phase: Phase = .starting

    /// The account, while someone is signed in.
    var me: Me? {
        guard case .signedIn(let me) = phase else { return nil }
        return me
    }
    /// A sign-in is under way.
    @Published private(set) var busy = false
    /// The terms' dialog is up (`Terms.swift`), waiting for an answer.
    @Published private(set) var termsAsked = false
    private var termsAnswer: CheckedContinuation<Bool, Never>?

    private let world: World

    init(world: World) {
        self.world = world
        // A sign-in that ends in the middle (the server refuses the token,
        // or will not renew it) puts the sign-in screen up, whatever
        // screen was showing.
        world.gate.onEnded = { [weak self] in
            Task { @MainActor in
                self?.phase = .signedOut(note: "Your sign-in ended. Sign in again.")
            }
        }
        // Any call answered `gone`: the account is being deleted, from this
        // phone or another. The same end as a deletion asked here.
        world.gate.onGone = { [weak self] in
            Task { @MainActor in
                self?.world.trail.mark("account: gone")
                self?.endDeleted()
            }
        }
    }

    /// The line on the sign-in screen once the account is being deleted.
    nonisolated static let deletedNote = "Your account is being deleted."

    /// The API's answer to every call by an account being deleted (403
    /// `gone`; a 404 `gone` is a thing that is not there).
    nonisolated static func isGone(_ error: ApiError) -> Bool {
        error.status == 403 && error.code == "gone"
    }

    /// The account as the server answered a change to it (a new name, a
    /// username): the screens draw it at once.
    func update(_ me: Me) {
        guard case .signedIn = phase else { return }
        phase = .signedIn(me)
    }

    /// "Delete account", confirmed: `DELETE /me` with `{"confirm":
    /// "delete"}`. On `{"deleting": true}` the app forgets its tokens and
    /// what waits to be sent, and shows the sign-in screen with one line.
    /// Throws, with words for the person, when the server refused.
    func deleteAccount() async throws {
        world.trail.mark("account: delete sent")
        guard try await world.backend.deleteAccount(confirm: "delete") else {
            throw ApiError(status: 200, code: nil, message: "The server's answer could not be read.")
        }
        world.trail.mark("account: deleting")
        endDeleted()
    }

    /// The end of a deleted account: no tokens, no queue, no kept flow.
    private func endDeleted() {
        world.gate.signOut()
        world.outbox.dropEverything()
        phase = .signedOut(note: Session.deletedNote)
    }

    /// Reads the account. The app's start, "Try again", and what follows a
    /// sign-in.
    func load() async {
        guard world.gate.signedIn else {
            phase = .signedOut(note: nil)
            return
        }
        if case .signedIn = phase {
            // Already open: read again behind the screen.
        } else {
            phase = .starting
        }
        do {
            let me = try await world.backend.me()
            world.trail.mark("start: account read")
            phase = .signedIn(me)
        } catch let error as ApiError {
            if error.status == 401 {
                phase = .signedOut(note: "Your sign-in ended. Sign in again.")
            } else if Session.isGone(error) {
                // `onGone` drops the rest; the screen says it at once.
                phase = .signedOut(note: Session.deletedNote)
            } else if error.status == 403 && error.code == "not_admitted" {
                // This address is not let in: nobody is stuck retrying it.
                world.gate.signOut()
                phase = .signedOut(note: "\(error.message) Sign in with a different Google account.")
            } else if error.status == 404 {
                phase = .failed("The app is not open on this server yet.")
            } else {
                phase = .failed(error.message)
            }
        } catch {
            world.trail.mark("start: failed (\(Auth.kind(error)))")
            phase = .failed("The app could not start. Try again.")
        }
    }

    /// Signs in. `sheet` opens the address in iOS's sign-in sheet and
    /// answers with the address Cognito sent the person back to.
    func signIn(sheet: (URL) async throws -> URL) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let start = try await world.gate.begin()
            let callback: URL
            do {
                callback = try await sheet(start.url)
            } catch {
                // The person closed the sheet, or it could not open.
                world.trail.mark("signin: sheet closed (\(Auth.kind(error)))")
                return
            }
            world.trail.mark("signin: sheet returned")
            try await world.gate.finish(callback: callback, start: start)
            await load()
        } catch let refused as SignInRefused {
            phase = .signedOut(note: "\(refused.reason) Sign in with a different Google account.")
        } catch {
            world.trail.mark("signin: failed (\(Auth.kind(error)))")
            phase = .signedOut(note: "Sign-in did not finish. Check the connection and try again.")
        }
    }

    func signOut() {
        world.gate.signOut()
        phase = .signedOut(note: "Signed out. Choose an account to sign in again.")
    }

    // MARK: The terms first

    /// Before a write: true when the terms in force are accepted, asking
    /// first when they are not; false when the person said no, and nothing
    /// is to be sent. `changed`: the server refused a write with
    /// `terms_required` although the account said they were accepted, so
    /// the account is read again and the person is asked all the same.
    /// Throws when the acceptance could not be saved.
    func termsFirst(changed: Bool = false) async throws -> Bool {
        guard case .signedIn(var me) = phase else { return false }
        if changed {
            me = try await world.backend.me()
            phase = .signedIn(me)
        } else if !me.termsRequired {
            return true
        }
        // One dialog at a time: a second tap while it is up sends nothing.
        guard termsAnswer == nil else { return false }
        world.trail.mark("terms: asked")
        let yes = await withCheckedContinuation { answer in
            termsAnswer = answer
            termsAsked = true
        }
        guard yes else {
            world.trail.mark("terms: declined")
            return false
        }
        do {
            let now = try await world.backend.acceptTerms(version: me.termsCurrent ?? "")
            phase = .signedIn(now)
            world.trail.mark("terms: accepted")
            return true
        } catch let error as ApiError where error.code == "stale_terms" {
            // They changed between the read and the yes: the next tap asks
            // with the version in force.
            world.trail.mark("terms: changed meanwhile")
            if let fresh = try? await world.backend.me() {
                phase = .signedIn(fresh)
            }
            throw ApiError(status: error.status, code: error.code, message: "The terms changed a moment ago. Tap again to accept them.")
        } catch {
            world.trail.mark("terms: not saved")
            throw error
        }
    }

    /// The dialog's two buttons.
    func answerTerms(_ yes: Bool) {
        termsAsked = false
        let answer = termsAnswer
        termsAnswer = nil
        answer?.resume(returning: yes)
    }
}
