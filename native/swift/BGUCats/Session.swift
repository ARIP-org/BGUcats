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
    /// A sign-in is under way.
    @Published private(set) var busy = false

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
}
