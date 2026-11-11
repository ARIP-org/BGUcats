import AuthenticationServices
import Capacitor
import UIKit

/// Sign-in through the system's own browser sheet.
///
/// Google refuses to sign anyone in inside an app's web view, and it is
/// right to: the app could read the password. ASWebAuthenticationSession is
/// what iOS offers instead. The sheet belongs to the system, the app never
/// sees what is typed into it, and it shares Safari's sign-ins. iOS asks
/// first: "BGU Cats" wants to use "amazoncognito.com" to sign in.
///
/// The page calls `start` with Cognito's authorize address and the scheme of
/// the address Cognito sends people back to (web/app.js, `login`). The
/// session watches for that scheme itself, so it is registered nowhere and
/// no other app can claim the answer. `start` resolves with the whole
/// address Cognito answered with; the page reads the code out of it.
@objc(WebAuthPlugin)
public class WebAuthPlugin: CAPPlugin, CAPBridgedPlugin, ASWebAuthenticationPresentationContextProviding {
    public let identifier = "WebAuthPlugin"
    public let jsName = "WebAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise)
    ]

    // Kept while the sheet is up: a session nobody holds is closed at once.
    private var session: ASWebAuthenticationSession?

    @objc func start(_ call: CAPPluginCall) {
        guard let address = call.getString("url"),
              let url = URL(string: address),
              url.scheme == "https",
              let scheme = call.getString("callbackScheme"),
              !scheme.isEmpty
        else {
            call.reject("start needs an https url and a callbackScheme")
            return
        }

        DispatchQueue.main.async {
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { [weak self] answer, error in
                self?.session = nil
                if let answer = answer {
                    call.resolve(["url": answer.absoluteString])
                } else if let error = error as? ASWebAuthenticationSessionError, error.code == .canceledLogin {
                    // The person closed the sheet. Not a failure to report.
                    call.reject("Sign-in was cancelled.", "CANCELLED")
                } else {
                    call.reject(error?.localizedDescription ?? "Sign-in did not finish.")
                }
            }
            session.presentationContextProvider = self
            // Safari's cookies are shared on purpose: a Google account
            // already signed in on the phone is offered, not asked for again.
            session.prefersEphemeralWebBrowserSession = false
            self.session = session
            if !session.start() {
                self.session = nil
                call.reject("The sign-in sheet could not be opened.")
            }
        }
    }

    public func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
