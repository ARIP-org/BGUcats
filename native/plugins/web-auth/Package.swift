// swift-tools-version: 5.9
import PackageDescription

// The name is the one Capacitor's CLI derives from the npm name
// (bgucats-web-auth) when it writes ios/App/CapApp-SPM/Package.swift.
let package = Package(
    name: "BgucatsWebAuth",
    platforms: [.iOS(.v15)],
    products: [
        .library(
            name: "BgucatsWebAuth",
            targets: ["WebAuthPlugin"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0")
    ],
    targets: [
        .target(
            name: "WebAuthPlugin",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm")
            ],
            path: "ios/Sources/WebAuthPlugin")
    ]
)
