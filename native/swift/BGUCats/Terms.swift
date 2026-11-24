import SwiftUI

/// The terms come before anything a person writes for others to read:
/// asked once, where the first such write happens (`Session.termsFirst`),
/// as the web app does (`web/social/terms.js`). The words are the web
/// app's (`web/i18n/en.json`, `terms.*`), in English.
enum Terms {
    static let title = "Before you post"
    static let body = "Posts, names and proposals are shared with the campus. By going on you accept BGU Cats' terms (draft, for the beta)."
    static let accept = "Accept and go on"
}

extension View {
    /// The system's own dialog, up while the session waits for an answer.
    func termsDialog(_ session: Session) -> some View {
        modifier(TermsDialog(session: session))
    }
}

private struct TermsDialog: ViewModifier {
    @ObservedObject var session: Session

    func body(content: Content) -> some View {
        content.alert(
            Terms.title,
            isPresented: Binding(get: { session.termsAsked }, set: { shown in
                // Closed without a button: the same as "Cancel".
                if !shown && session.termsAsked {
                    session.answerTerms(false)
                }
            })
        ) {
            Button(Terms.accept) {
                session.answerTerms(true)
            }
            .accessibilityIdentifier("terms.accept")
            Button("Cancel", role: .cancel) {
                session.answerTerms(false)
            }
            .accessibilityIdentifier("terms.cancel")
        } message: {
            Text(Terms.body)
        }
    }
}
