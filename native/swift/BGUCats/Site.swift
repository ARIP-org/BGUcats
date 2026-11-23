import Foundation

/// Where this app belongs. Every build so far is staging's
/// (.github/workflows/ios.yml, `SITE`; a test holds the two together).
/// When production opens (L3) this is what changes.
enum Site {
    static let origin = URL(string: "https://d2rysfyl47qmmz.cloudfront.net")!

    /// Cognito answers a sign-in at an address only this app can mean: its
    /// bundle id as a scheme (infra/main/api.tf, `native_app_redirect`).
    static let scheme = "org.arip.bgucats"
    static let redirect = "org.arip.bgucats://signin"
}

/// The deployment's public config.json, the same one the web app reads.
/// Nothing in it is secret.
struct SiteConfig: Codable, Equatable {
    let userPoolClientId: String
    let cognitoDomain: String
}
