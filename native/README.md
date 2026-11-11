# native/: the iPhone app

`web/` packed with [Capacitor](https://capacitorjs.com) so it can be
installed from TestFlight. One codebase: there is no second copy of the
app here, only the shell around it. How it is built, what a build costs and
how it reaches a phone: `docs/deploy.md`, "The iPhone app".

| | |
|---|---|
| `package.json`, `package-lock.json` | Capacitor, pinned to exact versions. `npm ci` installs what the lock file says |
| `capacitor.config.json` | the bundle ID `org.arip.bgucats`, the app's name, where the packed files are |
| `www/` | not in git: `scripts/native_bundle.py` makes it from `web/` |
| `ios/` | the Xcode project `npx cap add ios` generated (Swift packages, no CocoaPods), with the edits below |
| `plugins/web-auth/` | our one native plugin: sign-in through iOS's own sheet. A local npm package, so `cap sync` wires it in like any other plugin |

## The sign-in plugin

Google refuses to sign anyone in inside an app's web view. iOS offers
`ASWebAuthenticationSession` for exactly this: a sheet that belongs to the
system, shares Safari's sign-ins, and that the app cannot read. The plugin
is the forty lines of Swift that open it
(`plugins/web-auth/ios/Sources/WebAuthPlugin/WebAuthPlugin.swift`). The
page calls `Capacitor.Plugins.WebAuth.start({ url, callbackScheme })` and
gets back the address Cognito answered with (`web/app.js`, `login`).

It is a package of its own, not a file in the Xcode project, so nothing in
`ios/App/App.xcodeproj` is edited by hand: `package.json` depends on it by
path, and `npx cap sync ios` writes it into `CapApp-SPM/Package.swift` and
into the list of plugin classes the app registers at start. Its Swift
package must keep the name the CLI derives from the npm name
(`bgucats-web-auth` → `BgucatsWebAuth`); `tests/native` holds that.

No Mac means it is compiled and started by the `simulator` job, which
fails if the page does not find the plugin, and tried by a person only in
a TestFlight build.

## What was changed in the generated project

Everything else in `ios/` is Capacitor's template, untouched.

- `App/App/Info.plist`: why the app asks for the camera, the microphone
  and the location, and `ITSAppUsesNonExemptEncryption` so App Store
  Connect does not ask about encryption on every build.
- `App/App.xcodeproj/project.pbxproj`: iPhone only
  (`TARGETED_DEVICE_FAMILY = 1`) and version `0.1.0`.
- `App/App/Assets.xcassets`: the icon and the launch image, drawn from
  `web/icon.svg` by `scripts/native_assets.py`.

`tests/native` checks the three that App Store Connect refuses a build
over.

## Working on it without a Mac

The project is edited as text. `.github/workflows/ios.yml` builds it and
starts it in an iPhone simulator on every pull request that touches this
folder; the run keeps a screenshot and the app's log.

On any machine with Node 22:

```bash
python scripts/native_bundle.py --site https://d2rysfyl47qmmz.cloudfront.net
cd native && npm ci && npx cap sync ios
```

leaves the project as the runner builds it. `cap sync` copies `www/` into
`ios/App/App/public` (not in git) and rewrites `CapApp-SPM/Package.swift`
from the installed plugins.

## A new Capacitor version, or a plugin

Change `package.json`, run `npm install` and `npx cap sync ios`, commit
`package-lock.json` and `Package.swift` together. The three `@capacitor/*`
packages always move as one.
