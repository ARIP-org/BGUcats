# native/swift/: the iPhone app, in Swift

The member app rewritten for iPhone (`docs/ROADMAP.md`, 2g). **It is what
TestFlight gets** (the owner, 2026-11-23): unfinished, in the same app as
the packed one it replaces (`native/ios/`), so every screen is seen on
the phone as it lands. Built so far: the frame (four tabs of the system's
own controls, so the glass is iOS's), signing in, Home with the feed
(posts, their photos, a like, a post's menu: Delete on one's own, Report
on anyone else's), the profile's first rows, and "App info".
Cats and Scan a cat say "Not built yet".

| File | |
|---|---|
| `BGUCatsApp.swift` | the start, and `World`: everything a screen reads from outside itself |
| `Site.swift` | which deployment the app belongs to (staging), and where Cognito answers |
| `Auth.swift` | signing in: PKCE, the tokens in the keychain, renewing them |
| `Backend.swift` | the member API, and the made-up one UI tests get |
| `Models.swift` | what the API answers with, read field by field |
| `Session.swift` | who is signed in, and whether the app has started |
| `RootView.swift` | the first screen by state, the tabs, the profile |
| `SignInView.swift`, `FeedView.swift`, `AppInfoView.swift` | those screens |
| `ReportView.swift` | the report sheet: the server's six reasons, an optional note |
| `Ulid.swift` | an id made on the phone (a report's), so a retry is the same request |
| `Photos.swift` | loading a picture, and the drawn ones UI tests get |
| `Trail.swift` | the app's own account of what it did |

| | |
|---|---|
| `BGUCats.xcodeproj/` | the project, written by hand: nobody here has Xcode. Two targets, the app and its UI tests |
| `BGUCats/` | the app. Every file in this folder is compiled into it |
| `BGUCatsUITests/` | UI tests that open every screen in a simulator and keep a picture of each, in light and dark |

## Working on it without a Mac

Swift cannot be compiled on Linux. The `swift` job of
`.github/workflows/ios.yml` is the compiler and the eyes: on every pull
request that touches `native/`, a macOS runner builds the app, runs the UI
tests in an iPhone simulator, and keeps the pictures as the run's
artifact `ios-swift` (`home-light.png`, `app-info-dark.png`, ...). A
compile error or a screen that does not open fails the job, and its log
says where.

The same job then **archives the app as the upload will**
(`scripts/ios_archive.py`): a Release build for a real iPhone, unsigned,
and a look at what came out (bundle id, build number, iOS version, icon,
privacy manifest). The `testflight` job runs the same script, so what a
pull request archived is what the owner's build uploads.

**A new Swift file needs no edit to the project:** both folders are read
whole (Xcode's "file system synchronized" groups). `tests/native` holds
the project file to what a hand edit breaks quietly: every reference
defined, one iOS version, nothing that signs.

## Rules of this app

- **One iOS version exactly, the newest** (the owner): the deployment
  target is 26.0, stated once per configuration in the project.
- **The system's own controls and materials.** No drawn glass, no copied
  tab bar: `TabView`, `NavigationStack`, `List`, the system's button
  styles. They follow the phone's settings for transparency, contrast and
  text size by themselves.
- **No screen without a picture.** A screen comes with its step in
  `ScreensUITests`, which keeps its picture in both looks.
- **A UI test reads no network and keeps nothing.** The app started with
  `-uiTesting` gets a made-up world (`World.standIn()`): a clock that
  stands still, a trail kept in memory, a made-up member with three
  made-up posts (`StandInBackend`), and pictures that are drawn
  (`DrawnPhotos`), so two pictures of one screen are the same picture.
  `-signedOut` starts it with nobody signed in. A new screen that reads
  the API adds its canned answers to `StandInBackend`. The network is
  reached from three files only (`Auth`, `Backend`, `Photos`), each
  behind a protocol; a test holds that. The look is asked of the app (`-look dark`), and
  the test checks each picture's brightness: asking the simulator for
  dark did nothing on the first run, and ten light pictures passed.
- **The trail** (`Trail.swift`) is the web app's, with its limits: the
  last eighty lines, what happened and never who. "App info" shows it.
- **The same app to Apple:** the bundle id is the packed app's,
  `org.arip.bgucats`, and the version is above it, so a build is an
  update. Nothing in the project signs it; a simulator build is signed
  "to run locally" by Xcode, with no team and no certificate, and the
  upload signs at export.
- **A screen not built says so** (`NotBuiltYet`), and never looks
  broken: the owner is using this app while it is being written.
- **The privacy manifest** (`BGUCats/PrivacyInfo.xcprivacy`) says what
  the app reads and sends. Today: the trail in UserDefaults; and, since
  it signs in, the account (email, name, user id), what a person does (a
  like), and the servers' counters and logs. Photos, location, friends
  and the phone's notification address join it with the screen that
  first sends them: a test fails a pull request that adds one without
  the other (`docs/privacy-data.md` has the answers). A report and its
  note are content a person made, a kind already declared for the like.
- **Signing in is the web app's, in iOS's own sheet** (`Auth.swift`,
  `web/lib/auth.js`): Cognito's page, authorization code with PKCE,
  straight to Google with its account chooser, answered at
  `org.arip.bgucats://signin`. Never in a web view: Google refuses that.
  The tokens are in the keychain, on this phone only. Signing out forgets
  them and stays in the app.
- **A sign-in that ends puts the sign-in screen up.** When the API
  answers 401, or Cognito refuses to renew (400, 401), the tokens go and
  the session is told (`Gate.onEnded`), so nobody is left on a feed whose
  every tap fails. A 429 or a 5xx from Cognito, or no connection, ends
  nothing: the call says the server could not be reached, and no stale
  token is sent, because the API's 401 to it would read as a sign-in
  that ended.
- **An identifier goes on the element itself, never on a stack around
  others.** On a container SwiftUI hands the identifier to everything
  inside, over their own: a post card's stack named `post.p1` left no
  `like.p1` to find (2026-11-23).
- **It belongs to staging** (`Site.swift`), as every build so far. The
  site's public `config.json` says which Cognito; it is read at launch
  and the last one read is kept for a launch with no signal.
- **Every state of the start says what it is** (`RootView`): loading,
  the sign-in screen with the reason the last sign-in ended, the tabs,
  or "The app could not start" with Try again, App info and Sign out.
  Every call gives up after twenty seconds.
- **A post's menu is the system's** (`Menu` on an ellipsis in the
  card's header). Delete, on the member's own post, asks with the
  system's alert, takes the card off at once and puts it back with the
  server's words if it refuses. Report, on anyone else's, opens a sheet
  with the server's fixed reasons (`src/common/reports.py`) in the web
  app's words and order, and an optional note of up to 280 characters;
  the report's id is made when the sheet opens, and the answer is always
  the same thank you. Neither asks for the terms: the API does not. The
  trail says "post: deleted" and "report: sent (spam)", never which post
  or what the note said.
- **The trail never says who.** A call is marked by its kind and its
  status ("api: feed 200 in 240 ms"), never by its address; a failure by
  its kind and number. A test reads every `trail.mark`.

## Not here yet

In the feed: friends' votes on a name (the API sends those cards; this
app skips them for now), the area, and
accepting the terms (a like before that is refused, and the app shows the
server's words). Then capture, cats, the rest of profile, the
recognition model, and a string catalog for the four languages. Each is
its own issue, in the plan's order.
