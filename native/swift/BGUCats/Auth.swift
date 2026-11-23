import CryptoKit
import Foundation
import Security

/// Signing in: Cognito's hosted page, authorization code with PKCE, the
/// same as the web app (web/lib/auth.js). The page opens in iOS's own
/// sign-in sheet, never in a web view of the app's: Google refuses that.

struct Tokens: Codable, Equatable {
    var idToken: String
    var refreshToken: String?
    var expiresAt: Date
}

/// Where the tokens are kept.
protocol Vault {
    func read() -> Tokens?
    func keep(_ tokens: Tokens)
    func drop()
}

/// The phone's keychain: kept across launches, never in a backup that
/// leaves this phone, readable only by this app.
final class KeychainVault: Vault {
    private let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "org.arip.bgucats.signin",
        kSecAttrAccount as String: "tokens",
    ]

    func read() -> Tokens? {
        var ask = query
        ask[kSecReturnData as String] = true
        ask[kSecMatchLimit as String] = kSecMatchLimitOne
        var found: CFTypeRef?
        guard SecItemCopyMatching(ask as CFDictionary, &found) == errSecSuccess else { return nil }
        guard let data = found as? Data else { return nil }
        return try? JSONDecoder().decode(Tokens.self, from: data)
    }

    func keep(_ tokens: Tokens) {
        guard let data = try? JSONEncoder().encode(tokens) else { return }
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    func drop() {
        SecItemDelete(query as CFDictionary)
    }
}

/// For UI tests: nothing is written to the phone.
final class MemoryVault: Vault {
    private var kept: Tokens?

    func read() -> Tokens? { kept }
    func keep(_ tokens: Tokens) { kept = tokens }
    func drop() { kept = nil }
}

/// The address to open in the sign-in sheet, and the secret that proves
/// the answer is for the one who asked.
struct SignInStart {
    let url: URL
    let verifier: String
}

/// Cognito turned the sign-in away, and why, in words for a person.
struct SignInRefused: Error {
    let reason: String
}

/// The token endpoint answered, and not with tokens.
struct TokenRefused: Error {
    let status: Int
}

/// Signing in and out, as the screens see it.
protocol Gate: AnyObject {
    var signedIn: Bool { get }
    func begin() async throws -> SignInStart
    func finish(callback: URL, start: SignInStart) async throws
    func signOut()
}

final class Auth: Gate {
    static let configKey = "bgucats.config"

    private let vault: Vault
    private let trail: Trail
    private let now: () -> Date
    private let defaults: UserDefaults
    private var known: SiteConfig?

    init(vault: Vault, trail: Trail, now: @escaping () -> Date = Date.init, defaults: UserDefaults = .standard) {
        self.vault = vault
        self.trail = trail
        self.now = now
        self.defaults = defaults
    }

    var signedIn: Bool {
        vault.read() != nil
    }

    /// Signing out forgets this app's tokens. There is no trip to
    /// Cognito's sign-out page: the next sign-in asks Google which account
    /// to use anyway.
    func signOut() {
        vault.drop()
        trail.mark("signin: signed out")
    }

    /// The site's config.json, read once a launch. With no signal, the one
    /// kept from the last launch.
    func config() async throws -> SiteConfig {
        if let known {
            return known
        }
        do {
            var request = URLRequest(url: Site.origin.appendingPathComponent("config.json"))
            request.timeoutInterval = 15
            request.cachePolicy = .reloadIgnoringLocalCacheData
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            let fresh = try JSONDecoder().decode(SiteConfig.self, from: data)
            defaults.set(data, forKey: Auth.configKey)
            known = fresh
            return fresh
        } catch {
            if let kept = defaults.data(forKey: Auth.configKey),
               let old = try? JSONDecoder().decode(SiteConfig.self, from: kept) {
                trail.mark("config: not read (\(Auth.kind(error))), using the kept one")
                return old
            }
            trail.mark("config: not read (\(Auth.kind(error)))")
            throw error
        }
    }

    func begin() async throws -> SignInStart {
        let config = try await config()
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let verifier = Auth.base64url(Data(bytes))
        let challenge = Auth.base64url(Data(SHA256.hash(data: Data(verifier.utf8))))

        var parts = URLComponents()
        parts.scheme = "https"
        parts.host = config.cognitoDomain
        parts.path = "/oauth2/authorize"
        parts.queryItems = [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: config.userPoolClientId),
            URLQueryItem(name: "redirect_uri", value: Site.redirect),
            URLQueryItem(name: "scope", value: "openid email profile"),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            // Straight to Google: it is the only way in.
            URLQueryItem(name: "identity_provider", value: "Google"),
            // Google's account chooser, every time. Without it someone
            // turned away could never pick a different account.
            URLQueryItem(name: "prompt", value: "select_account"),
        ]
        guard let url = parts.url else {
            throw URLError(.badURL)
        }
        trail.mark("signin: started")
        return SignInStart(url: url, verifier: verifier)
    }

    /// What Cognito answered the sign-in with: a code to trade for tokens,
    /// or why not.
    func finish(callback: URL, start: SignInStart) async throws {
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? {
            items.first { $0.name == name }?.value
        }
        if let error = value("error") {
            // Almost always the sign-up check refusing an address that is
            // not let in. Cognito puts its own plumbing before the reason.
            let said = (value("error_description") ?? error).replacingOccurrences(of: "+", with: " ")
            let reason = said
                .replacingOccurrences(of: "PreSignUp failed with error", with: "", options: [.caseInsensitive])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            vault.drop()
            trail.mark("signin: refused")
            throw SignInRefused(reason: reason.isEmpty ? "Sign-in was refused." : reason)
        }
        guard let code = value("code") else {
            trail.mark("signin: no code came back")
            throw SignInRefused(reason: "Sign-in did not finish.")
        }
        _ = try await exchange([
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Site.redirect,
            "code_verifier": start.verifier,
        ])
        trail.mark("signin: tokens kept")
    }

    /// The token every API call carries, renewed when it has run out. Nil:
    /// signed out.
    func idToken() async -> String? {
        guard let tokens = vault.read() else { return nil }
        if now() < tokens.expiresAt {
            return tokens.idToken
        }
        guard let refresh = tokens.refreshToken else { return nil }
        do {
            return try await exchange(["grant_type": "refresh_token", "refresh_token": refresh]).idToken
        } catch let refused as TokenRefused {
            trail.mark("signin: renewal refused (\(refused.status))")
            vault.drop()
            return nil
        } catch {
            // No connection is not a refused sign-in: keep it for when the
            // phone is back. The stale token fails its call, which says so.
            trail.mark("signin: renewal not reached (\(Auth.kind(error)))")
            return tokens.idToken
        }
    }

    private func exchange(_ fields: [String: String]) async throws -> Tokens {
        let config = try await config()
        guard let url = URL(string: "https://\(config.cognitoDomain)/oauth2/token") else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        // Cognito answers in well under a second.
        request.timeoutInterval = 12
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "content-type")
        var all = fields
        all["client_id"] = config.userPoolClientId
        request.httpBody = Auth.form(all)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let answer = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard status == 200, let idToken = answer?["id_token"] as? String else {
            throw TokenRefused(status: status)
        }
        let seconds = (answer?["expires_in"] as? NSNumber)?.doubleValue ?? 3600
        let tokens = Tokens(
            idToken: idToken,
            // A renewal does not return a new refresh token: keep the old.
            refreshToken: (answer?["refresh_token"] as? String) ?? vault.read()?.refreshToken,
            expiresAt: now().addingTimeInterval(seconds - 60)
        )
        vault.keep(tokens)
        return tokens
    }

    // ------------------------------------------------------------ helpers

    static func base64url(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    /// One value, safe inside a query or a form.
    static func encode(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    static func form(_ fields: [String: String]) -> Data {
        let pairs = fields.keys.sorted().map { "\(encode($0))=\(encode(fields[$0] ?? ""))" }
        return Data(pairs.joined(separator: "&").utf8)
    }

    /// What kind of failure, for the trail: a kind and a number, never the
    /// address asked or anything it carried.
    static func kind(_ error: Error) -> String {
        if let failure = error as? URLError {
            switch failure.code {
            case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed:
                return "no connection"
            case .timedOut:
                return "timed out"
            default:
                return "network \(failure.code.rawValue)"
            }
        }
        let plain = error as NSError
        return "\(plain.domain) \(plain.code)"
    }
}

/// For UI tests: signed in or not as the test asks, and no network.
final class StandInGate: Gate {
    private(set) var signedIn: Bool

    init(signedIn: Bool) {
        self.signedIn = signedIn
    }

    func begin() async throws -> SignInStart {
        throw URLError(.notConnectedToInternet)
    }

    func finish(callback: URL, start: SignInStart) async throws {}

    func signOut() {
        signedIn = false
    }
}
