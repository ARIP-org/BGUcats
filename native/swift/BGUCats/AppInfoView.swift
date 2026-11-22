import SwiftUI
import UIKit

/// "App info": what this app was doing on this phone, to read or to copy to
/// whoever is fixing it. The text is the app's own, in English, as it was
/// kept.
struct AppInfoView: View {
    let world: World
    /// As it was when the page opened: reading it must not add to it.
    @State private var text = ""
    @State private var copied = false

    init(world: World) {
        self.world = world
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("What the app was doing on this phone lately, for whoever is fixing it. It has no name, no address and no photos, and it stays on this phone unless you copy it.")
                    .foregroundStyle(.secondary)

                Button {
                    UIPasteboard.general.string = text
                    copied = true
                } label: {
                    Label(copied ? "Copied" : "Copy app info", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.glass)
                .accessibilityIdentifier("app-info.copy")

                Text(text)
                    .font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .environment(\.layoutDirection, .leftToRight)
                    .accessibilityIdentifier("app-info.text")
            }
            .padding()
        }
        .navigationTitle("App info")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if text.isEmpty {
                text = AppInfo.text(world: world)
            }
        }
    }
}

enum AppInfo {
    /// The header says what kind of app and phone this is; the lines under
    /// it are the trail. Nothing here says who.
    static func text(world: World) -> String {
        let system = ProcessInfo.processInfo.operatingSystemVersion
        let header = [
            "BGU Cats, app info, \(ISO8601DateFormatter().string(from: world.now()))",
            "kind: iPhone app (Swift)",
            "version: \(world.version)",
            "system: iOS \(system.majorVersion).\(system.minorVersion).\(system.patchVersion)",
            "",
        ]
        return (header + world.trail.lines).joined(separator: "\n")
    }
}
