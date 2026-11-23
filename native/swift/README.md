# native/swift/: the iPhone app, in Swift

The member app rewritten for iPhone (`docs/ROADMAP.md`, 2g). It sits
**beside** today's packed app (`native/ios/`), which stays what TestFlight
gets until this one has its screens. Built so far: the frame (four tabs
of the system's own controls, so the glass is iOS's) and "App info".

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
  stands still and a trail kept in memory, so two pictures of one screen
  are the same picture. A screen that reads the API gets its canned
  answers the same way. The look is asked of the app (`-look dark`), and
  the test checks each picture's brightness: asking the simulator for
  dark did nothing on the first run, and ten light pictures passed.
- **The trail** (`Trail.swift`) is the web app's, with its limits: the
  last eighty lines, what happened and never who. "App info" shows it.
- **The same app to Apple:** the bundle id is the packed app's,
  `org.arip.bgucats`. Nothing in the project signs it; a simulator build
  is signed "to run locally" by Xcode, with no team and no certificate.

## Not here yet

Signing in, any call to the API, the feed, capture, cats, the rest of
profile, the recognition model, a string catalog for the four languages,
and TestFlight. Each is its own issue, in the plan's order.
