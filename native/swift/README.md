# native/swift/: the iPhone app, in Swift

The member app rewritten for iPhone (`docs/ROADMAP.md`, 2g). **It is what
TestFlight gets** (the owner, 2026-11-23): unfinished, in the same app as
the packed one it replaces (`native/ios/`), so every screen is seen on
the phone as it lands. Built so far: the frame (four tabs of the system's
own controls, so the glass is iOS's), signing in, Home with the feed
(posts, their photos, a like, the terms asked before the first like,
a post's menu: Delete on one's own, Report on anyone else's), Scan a
cat (photos taken or chosen, sent as one encounter, then "Which cat?",
the new-cat form for a cat that isn't here, and the post), Cats (the
gallery and a cat's page with its name poll), the profile's first rows,
and "App info".

| File | |
|---|---|
| `BGUCatsApp.swift` | the start, and `World`: everything a screen reads from outside itself |
| `Site.swift` | which deployment the app belongs to (staging), and where Cognito answers |
| `Auth.swift` | signing in: PKCE, the tokens in the keychain, renewing them |
| `Backend.swift` | the member API, and the made-up one UI tests get |
| `Models.swift` | what the API answers with, read field by field |
| `Session.swift` | who is signed in, whether the app has started, and the terms first |
| `Terms.swift` | the terms' words and their dialog |
| `RootView.swift` | the first screen by state, the tabs, the profile |
| `SignInView.swift`, `FeedView.swift`, `ScanView.swift`, `AppInfoView.swift` | those screens |
| `CatsView.swift`, `CatView.swift` | Cats: the gallery, and a cat's page pushed on the tab's stack |
| `NamePoll.swift` | the name poll on a cat's page: voting, taking a vote back, suggesting a name |
| `ScanPages.swift` | Scan a cat after "Send": "Which cat?", the new-cat form and the post |
| `ScanFlow.swift` | where the member is in Scan a cat after "Send", kept on the phone and checked before it is used |
| `ReportView.swift` | the report sheet: the server's six reasons, an optional note |
| `Outbox.swift` | the upload queue: photos kept on the phone until the server has them, then the pick or the proposal, and the post; and the scan flow beside it |
| `Places.swift` | where the phone is when a photo is taken |
| `Ulid.swift` | an id made on the phone (a report's, an encounter's, a photo's), so a retry is the same request |
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
- **The walk's waits are one `patience`, and the simulator is woken
  first.** A wait for something expected takes `patience`; a number of
  its own is only for something that must not come. A dialog's button is
  tapped through `.firstMatch`. Before the walk the job runs
  `WarmUpUITests`, which opens and closes the app until that is quick
  and asserts nothing: a simulator's first minutes failed the first walk
  three runs in a row with the app right (`docs/notes.md`).
- **A UI test reads no network and keeps nothing.** The app started with
  `-uiTesting` gets a made-up world (`World.standIn()`): a clock that
  stands still, a trail kept in memory, a made-up member with three
  made-up posts and a campus of three cats (`StandInBackend`: Shachor is
  the cat of the day, the member met Mitzi twice, and the third has no
  name, place, coat, description, grade or meeting), and pictures that are drawn
  (`DrawnPhotos`), so two pictures of one screen are the same picture.
  `-signedOut` starts it with nobody signed in, `-termsRequired` with
  the terms not accepted, `-termsChanged` with terms that changed after
  the account was read (the first like is refused). On Scan a cat the camera
  and the gallery hand out drawn photos, the place is made up
  (`StandInPlaces`), and the stand-in plays the four upload routes;
  `-uploadFailsOnce` makes the second photo's upload time out once,
  `-offline` reaches nothing, `-postNotReadyOnce` answers the first
  post `not_ready`, and `-flowBroken` leaves a kept flow that reads as
  one and is not whole (the new-cat form with a coat the server does not
  take). A post made is first in the stand-in's feed. The upload queue is the one thing it keeps,
  in the app's temporary folder, emptied at each launch unless
  `-keepQueue` asks for what the last launch left. What the stand-in was
  asked is at the end of App info, photos by number. A new screen that reads
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
  like), and the servers' counters and logs; since Scan a cat, photos
  and the precise place a photo was taken. Friends and the phone's
  notification address join it with the screen that first sends them: a
  test fails a pull request that adds one without the other
  (`docs/privacy-data.md` has the answers). A report and its note are
  content a person made, a kind already declared for the like.
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
- **The terms come before the first write** (`Session.termsFirst`, as
  `web/social/terms.js`): when `GET /me` says they are required, the
  system's dialog asks, with the web app's words; "Accept and go on"
  sends `POST /me/terms` with `terms.current` and the write goes on,
  "Cancel" sends nothing and counts nothing. A write refused with
  `terms_required` all the same (the terms changed since the account was
  read) reads the account again and asks once more, never shows the
  code. Taking a like back writes nothing others read and asks nothing.
  Each screen that writes asks the same way. The trail says "terms:
  asked", "accepted" or "declined".
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

- **What the app may ask the phone for** is in the project, one sentence
  each, in both configurations: the camera
  (`INFOPLIST_KEY_NSCameraUsageDescription`) and the place while the app
  is open (`INFOPLIST_KEY_NSLocationWhenInUseUsageDescription`). Asking
  without the sentence ends the app; the archive's look fails a build
  without them and prints them. The gallery is the system's picker,
  which needs no permission.
- **Scan a cat sends what the web app's upload queue sends**
  (`Outbox.swift`, `web/outbox.js`): ids made on the phone, the
  encounter with its first photo, then each photo's record, its bytes
  and the confirmation, three photos at a time. Each photo's file is
  written once to the app's own storage, with a small index beside it,
  and leaves only when the server has it; the queue goes on at the next
  launch with no tap. A failure says why on screen and holds up no other
  photo. A JPEG of 20 MB at most: a photo from the gallery is drawn again
  as one, which also leaves its own place behind, and it is sent with
  `origin: "gallery"` and no place. A camera photo carries the latest fix
  (rounded to three decimals) if the person allowed it and one has come;
  nothing waits for it. The trail says each step by kind and status
  ("upload: media 200", "upload: retry, timed out").
- **After "Send", the cat and the post** (`ScanPages.swift`, the web
  app's `web/social/scan.js` and its words). "Which cat?" opens from the
  sent photos: every cat of `GET /api/v1/cats` in a system `List` with
  its cover, a search field, "Not sure", and "A cat that isn't here",
  which opens the new-cat form (below). Then the post: the cat said, the photos in
  their order, a description of up to 280 characters as the server
  counts them (code points after NFKC, so "❤️" is two), "Add location"
  (on unless turned off), and "Post", which asks for the terms first.
  "Post" queues, behind the photos in the same queue, the pick
  (`POST /api/encounters/{id}/pick`) and then the post
  (`POST /api/v1/posts`, `postId` made once on the phone). Each waits
  until every photo of the encounter is confirmed and goes once;
  `not_ready` waits and goes again with no tap and nothing on screen,
  `already_posted` (another post of this encounter is on the server; a
  resent `postId` gets its own post back) counts as sent, and a post
  refused for good stays in the queue's index, its refusal on the
  Posted screen across launches, until the flow ends. **A pick is what
  `_record_pick` takes from an app with no model:** the cat chosen is
  the one cat shown, `ranked` is empty, `modelVersion` is `none`. "Not
  sure" sends no pick (nothing was shown, and the server refuses a pick
  that shows nothing; the web app sends none either) and a post with no
  claim. Leaving after "Send" without choosing makes no post. Home reads
  the feed again when a post reaches the server, so the post is first,
  marked "Being checked". The trail says "scan: cat chosen", "upload:
  pick 200", "upload: post 201", never a cat, the words or an id.
- **A cat that isn't here** (`NewCatPage`, the web app's `NewCat` and
  `endingWrites`): the encounter's photos, a name idea (optional, 24 at
  most as the server counts), the coat and where it hangs out (system
  menus, "Not said" until chosen; the places and "Somewhere else"), any
  traits (rows with a check, several allowed), the note that an admin
  looks first, and two ways out. The choices are the server's
  (`src/common/proposals.py`) and the places `web/regions.json`'s, copied
  into `Campus` (`Models.swift`) and held equal to both, with the web
  app's words, by a Linux test. **"Just add"** asks for the terms (a
  proposal is written for the campus) and queues the proposal alone;
  the screen says "Added", then "Thanks! An admin will look at your new
  cat." **"Add & post"** goes on to the post, which names the new cat
  by its name idea or "New cat", and whose "Post" asks for the terms and
  queues the proposal and the post. The proposal (`POST
  /api/v1/proposals`, `proposalId` made once on the phone and kept with
  the flow) waits for every photo to be confirmed, the post
  (`claim: {proposalId}`) for the proposal; `already_proposed` counts
  as sent, the daily limit (429) and any other refusal for good are
  said on the Added or Posted screen and stop the post that names it.
  **No pick**: nothing was shown, and the server refuses a pick that
  shows nothing. The trail says "scan: new cat", "upload: proposal
  200", "scan: post queued, a new cat", never the name idea, a place or
  an id.
- **The scan flow is kept and checked** (`ScanFlow.swift`): the
  encounter, its photos, the step, the cat, the new cat's answers and
  the words are written beside the queue (`flow.json`, with the photos'
  small pictures) at every change, so a closed app opens on the same
  page. What the last launch left is read field by field: one that is
  not whole (an id that is not a ULID, no photos, a post page with no
  cat chosen, a new cat's answer the server would not take) is dropped,
  the trail says so, and the tab opens empty.

- **Cats** (`CatsView.swift`, `CatView.swift`; the web app's
  `web/social/gallery.js` and `cat.js`, and their words). The gallery is
  every cat of `GET /cats` in a `LazyVGrid` of two columns: cover, shown
  name (or "A cat with no name yet"), its area; above them the cat of
  the day, while nothing is searched. `.searchable` filters by name and a
  system `Menu` sorts, both on the phone: the web app's five sorts in its
  order and words, "Highest GPA" first and only when some cat has a
  grade (the server sends none with the `gpa` flag off), a tie going to
  the cat seen last. Pull to refresh. Each state says what it is:
  loading, "No cats yet.", "No cat called “…”.", and "The cats could
  not be loaded." with Try again. A cat opens on the tab's
  `NavigationStack`, so Back finds the gallery as it was left. **A cat's
  page** (`GET /cats/{catId}`): its photos in a `TabView` of the page
  style, the name and what named it (the poll's summary as words: by
  vote, by the people who look after the cats, no name yet), "Usually
  near" its area, its coat, the description, the numbers in a
  `GroupBox` (posts, likes, last seen, first seen, and the GPA only when
  there is one), "You met" from `met` (how often, on how many days, the
  first and last day) and nothing when it is null; then its posts (`GET
  /cats/{catId}/posts`) on Home's `PostCard`, through the same
  `FeedModel` (its `Source` says which list) and `postActions` (the
  delete confirmation, the report sheet, a failure's words), so a like
  there asks for the terms as on Home. **A field the server left out, or
  sent as null, is left out of the page**: `Cat`'s added fields are
  optional, and no zero or dash stands in for one. `Cat` is what "Which
  cat?" reads: its new fields have defaults, so that page is as it was.
  The trail says "api: cats 200 in … ms", "api: cat 200 in … ms",
  "cats: 3 listed", "cats: opened a cat", "cat: 1 posts", never a cat's
  id, a name or a search word.
- **The name poll on a cat's page** (`NamePoll.swift`, the web app's
  `web/social/poll.js` and its `poll.*` words), between the cat's
  numbers and its posts: `GET /cats/{catId}/names`, the count of votes,
  the lead (or, when an admin set the name, the web app's sentence for
  that, and the poll still open below it), the options as rows in a
  `GroupBox` (most votes first, the leader marked "LEADING", the
  member's choice checked, their own name not checked yet "Being
  checked"), and a `TextField` with "Suggest" (24 characters as the
  server counts them). A tap on an option moves the member's vote (`PUT
  …/vote`), a tap on their choice takes it back (`DELETE …/vote`), and
  "Suggest" sends the name with runs of spaces made one (`POST
  …/names`); **each answer is the poll as it now is, and only that is
  drawn**: nothing is counted on the phone first. The poll's answer is
  also the newest word on the cat's name and on "Named by vote · 5 of
  8" above it, as in the web app. The terms come first for a vote or a
  suggestion, as for a like ("Cancel" sends nothing, `terms_required`
  asks once more); taking a vote back asks nothing, as the API. A
  refusal is said in the web app's words, never its code: `not_accepted`
  "That name was not accepted.", `try_again` (or `gone`) reads the poll
  again and says "The poll just changed. Try again.", `rate_limited`
  "That's enough for now. Try again later.". The stand-in's Mitzi has
  three options (her name leading, "Pilpel", and the member's own
  "Ptitim" being checked); it records "vote key", "vote key from old",
  "unvote key" and "suggest Name, new" (or "merged into key"), and a UI
  test reads them in App info. The trail says "poll: voted", "poll:
  vote taken back", "poll: suggested, being checked" (or "merged"), and
  "poll: vote refused (409)", never a name, a key or a cat.

## Not here yet

In the feed: friends' votes on a name (the API sends those cards; this
app skips them for now), the area, and a page with the full terms (the
dialog has their short text). In Scan a cat: the model and its three
guesses, "My proposals" (`GET /me/proposals`), video, and uploading
while the app is closed. On a cat's page: the map, and "Feed a cat".
Then the rest of profile, the recognition model, and a string catalog
for the four languages. Each is
its own issue, in the plan's order.
