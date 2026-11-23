import AuthenticationServices
import SwiftUI

/// Nobody is signed in. One button: Google, through iOS's own sign-in
/// sheet. "App info" is here too, because a sign-in that fails is exactly
/// when someone is asked to copy it.
struct SignInView: View {
    let world: World
    @ObservedObject var session: Session
    /// Why the last sign-in ended, if it did.
    let note: String?
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession

    var body: some View {
        NavigationStack {
            VStack(spacing: 18) {
                Spacer()
                Image(systemName: "cat.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.tint)
                    .accessibilityHidden(true)
                Text("BGU Cats")
                    .font(.largeTitle.bold())
                Text("Meet the campus cats, name them, and see who others met.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                if let note {
                    Text(note)
                        .font(.callout)
                        .multilineTextAlignment(.center)
                        .padding()
                        .frame(maxWidth: .infinity)
                        .background(Color(.secondarySystemFill), in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityIdentifier("sign-in.note")
                }
                Spacer()
                Button {
                    Task {
                        await session.signIn { url in
                            try await webAuthenticationSession.authenticate(using: url, callbackURLScheme: Site.scheme)
                        }
                    }
                } label: {
                    Text(session.busy ? "Signing in…" : "Sign in with Google")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                .controlSize(.large)
                .disabled(session.busy)
                .accessibilityIdentifier("sign-in.google")

                NavigationLink("App info") {
                    AppInfoView(world: world)
                }
                .font(.footnote)
            }
            .padding(24)
        }
    }
}
