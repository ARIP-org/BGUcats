# The client: `web/` and `native/`

One codebase, as now. The app the prototype shows is built in `web/`,
runs as the PWA and is packed into the iPhone app by `native/`. The
labeling desk stays what it is.

## Where it lives

```
web/
  index.html, app.js, …     today's shell: the desk and today's Capture. Unchanged
  app.html                  the member app's page (new)
  social/                   its modules, one per screen and one per shared part (new)
  lib/                      what both shells share, moved out of app.js (new):
                            auth, the API client, the photo-address cache
  tokens.css                every colour, radius, shadow and curve, per theme (new)
  i18n/                     en.json, he.json, ru.json, ar.json (new)
  regions.json              the campus regions (new, O12)
  vendor/                   the renderer (A4) and the font, with checksums (new)
  outbox.js, recognition.js, capture.js, install.js, sw.js   reused, extended
```

**Which page is the front door** is one setting, `frontDoor`, in the
site's public `config.json`: `desk` (today) or `app`. `index.html`'s boot
reads it and, for `app`, goes to `app.html` unless the address says
`?desk`. The bundle script writes `app` into the copy the iPhone app
carries. That is the whole switch: no platform branch, and with the
setting at `desk` nothing a person sees has changed. Production's flips
at L3. An admin reaches the desk from a row in the profile (G14).

`web/` still has no build step. `scripts/native_bundle.py` keeps copying
it as it is.

**Since E0:** `frontDoor` is written by `infra/main/web.tf` from
`variables.tf` (`front_door`; `app` on staging since 2026-11-13, when
the owner installed the staging site and it opened on the desk; `desk` in
production until L3). `?desk` keeps the
desk for the rest of the session. Cognito sends every sign-in back to the
site's root, where the desk's boot trades the code; a sign-in started on
`app.html` leaves its address in `sessionStorage` (`takeReturnTo` in
`web/lib/auth.js`) and is sent back there. A browser tab on `app.html` is
sent to the root for the install page, as the desk's tab is.
`infra/main/web.tf` uploads every file under `web/`, typed by extension,
instead of a list of names by hand.

## The renderer (A4)

Recommended: Preact with `htm` templates, as one file under
`web/vendor/`, with its checksum checked by a test, the way
`scripts/publish_model.py` checks ONNX Runtime. No CDN: the page holds
sign-in tokens, and the iPhone app must open with no signal.

Rules whichever option A4 picks:

- One module per screen in `web/social/`, each exporting one component.
  A screen fetches through the shared data layer, never with `fetch`.
- State that several screens share (the caller, the cats, the theme, the
  language, the friend list) lives in one small store module. No state in
  globals.
- After any wait, a screen checks it is still the one shown before it
  draws (`docs/notes.md`: a late answer drew the Queue over Cats; the
  same race exists in every screen here).

## Moving shared code out of `app.js`

`web/app.js` is one 2,200-line module with sign-in, the API client, the
photo cache and every desk screen inside it, none of it exported. The
member app needs the first three. Milestone E0 moves them to `web/lib/`
**without changing what they do**, and the desk imports them from there.
The existing browser tests are the proof; that pull request changes no
screen.

Reused as they are, through their existing factories: `createOutbox`,
`createRecognition`, the install page, the service worker.

## From the prototype to code

The prototype canvas (`README.md`) is the specification for how things
look and move; there is no frozen copy (O2, the owner). Its files are the
designer's tool's format, not code to ship, but every value in them is
exact. A milestone that copies values names the version it read.

- **`tokens.css`** comes from `themes()` in `Feed.dc.html`: four themes,
  each a set of custom properties on `:root[data-theme=…]` (since E0,
  generated from version `1794482957-a6b5`; 40 per theme, `bgu-dark` the
  default as in the prototype). No colour,
  radius or shadow is written anywhere else. (This is also Phase 3 of
  `docs/ROADMAP.md`, arriving early.)
- **Curves and timings** are in the prototype's styles and scripts: the
  page slide (`cubic-bezier(0.32, 0.72, 0, 1)`, 0.5 s), the spring that
  `makeSpring` samples into a `linear()` easing, the glass button's press
  (`bindGlass`). They become named properties in `tokens.css` too.
- **Layout.** The prototype is a fixed 402 × 874 frame with absolute
  positions. Phones are not. Every screen is rebuilt to flow: widths in
  percent or `fr`, the tab bar and top buttons placed with the safe-area
  insets, nothing positioned by a pixel count from the top of a
  fixed frame. A screenshot test at 375, 402 and 430 points wide catches
  what does not flow.
- **The cat photos in the prototype are samples** and are never
  committed (`CLAUDE.md`, "Do not"). Tests and screenshots use the seed
  campus's drawn shapes.
- **The font.** The prototype loads Inter from Google's servers. The app
  ships it from `web/vendor/` (it is under the Open Font License), for
  the same reasons as the renderer.
- **The mascot** (`Mascot.dc.html`) is an inline SVG with two poses and
  three coats; port it as a component.

## Direction and language from the first line

Hebrew and Arabic read right to left, and adding that to finished CSS is
a rewrite. So from E0:

- Only logical properties: `margin-inline-start`, `inset-inline-end`,
  `text-align: start`. A lint rule in the tests fails on `left`,
  `right`, `margin-left` and their kin in `web/social/` and
  `tokens.css`, with a short allowlist for things that are truly
  physical (the camera's brackets).
- `dir` and `lang` on the root follow the chosen language. Icons that
  point (back, forward, the "Watch" arrow) are mirrored; photos, the map
  and the mascot are not.
- Every string comes from `web/i18n/{lang}.json` through one `t(key,
  values)` function. No sentence is built by joining pieces: "met
  *Simba*" is one string with a placeholder, because the order differs
  by language. Plurals go through `Intl.PluralRules` ("1 cat lives
  here" / "2 cats live here" has more than two forms in Russian and
  Arabic). Dates and numbers go through `Intl`.
- English is complete first. A language is offered in the menu only when
  its file is complete and a native speaker has read it on a phone (O14).

## The data layer

One module, `web/social/data.js`, on top of the shared API client:

- **Reads** use the existing pattern: answer from memory if fresh, else
  show the last answer and redraw only if the new one differs
  (`cachedGet`).
- **Likes and votes** change on screen at once and are sent; a refusal
  puts the old state back and says why. They are not queued offline: a
  like made with no signal fails visibly.
- **Posts, proposals and picks** ride the outbox, with the encounter and
  its photos, so they survive a closed app and a dead signal. A post is
  shown in its author's feed from the phone's memory the moment "Post" is
  pressed, marked as sending, then as being checked, then plain.
- **The flags** from `GET /api/v1/me` decide what is offered. A screen
  whose flag is off is not in the navigation at all.

### The outbox learns new kinds

Today it knows one sequence: encounter → photo record → upload →
confirm, plus the pick. It gains generic queued requests (the proposal,
the post) that run **after** every photo of their encounter is confirmed.
Three things to keep true, all from past incidents:

- a photo's bytes are written to IndexedDB once and never rewritten;
- one item's failure never holds up another encounter's items;
- `isPermanent` treats `409` with `retry: true` as "not yet"
  (`04-api.md`).

The service worker's background copy of the upload steps (Chrome on
Android) is extended to the same kinds, or the new kinds are left to the
open app. Either is acceptable for the iPhone-first build; say which in
the pull request. **E3 chose the open app:** the worker still uploads
photos; the proposal and the post go the next time the app is open
(`after` in `web/outbox.js`). Each change to an encounter in the outbox is
one IndexedDB transaction since E3: a read and a separate write let the
queue's "pick sent" undo a post recorded in between.

## Capture, rebuilt on the same engine

The new flow's pages are new. Underneath are today's pieces:

- **The camera** is the in-page viewfinder Capture already has, restyled
  with the brackets and the paw shutter. The flash button is shown only
  where the browser reports a torch; on an iPhone's web view it does not,
  so it is hidden there until a native plugin is worth it.
- **"Which cat?"** takes its three candidates from `createRecognition`,
  as "Who did you meet?" does today. Each photo is embedded as it is
  taken. The grid below is every cat, the model's order first.
- **The pick** is recorded exactly as today, with the ranking that was
  shown, so the product-loop numbers in Stats stay comparable. Choosing
  from the grid, or "New cat", is an answer too.
- **The result survives a reload:** the encounter, its photos, the
  ranking and the page reached are kept with the outbox's state, as
  today's result screen is.
- With D12 on, a press keeps three frames; the page shows the first.

**Asking the phone** (`web/social/asking.js`, since 2026-11-13). The
flow's screen is drawn before anything is asked of the phone: the camera
on the camera page, then where the phone is, one question at a time. A
post started with "+" asks for the place once its page is there. A
question still unanswered when the app is closed is not asked again by
itself: the next launch says so, the phone's own camera button still
takes the photo, and "Add location" on a post, or "Try the live camera",
asks again. `docs/notes.md`, "The iPhone app", has why.

## States the design does not draw (G10)

Built plainly from the existing components, each with a screenshot for
the owner:

| State | What is shown |
|---|---|
| No model on this phone (first run, data saver, or the iPhone app before N1) | "Which cat?" opens on the grid of all cats, with no candidates row |
| No signal | the feed from memory with a quiet note; Capture works fully; likes and votes say they could not be sent |
| Feed, gallery, friends, posts: empty | the mascot and one line with the next thing to do. Friends (E7a): the podium with you alone, one line, and **Invite friends** |
| A post being sent | its photo with a progress ring; the outbox's own words for why it waits |
| A post, name or display name being checked | visible to its owner with "Being checked" |
| A post for a new cat, before an admin approves the cat (D7) | visible to its owner with "Waiting for an admin to confirm the new cat"; nobody else sees it |
| A cat with no GPA yet, or no feeding logged | "—"; "No feeding logged yet" |
| Not accepted | "This wasn't published" on the item, with no category. Removing it is one tap |
| A photo still uploading when "Post" is pressed | allowed; the post follows the photos |
| Sign-in refused (`not_admitted`) | the existing refusal screen, reworded |
| Terms not accepted | the terms page before anything else (G1) |

## What only the iPhone app has

`web/` knows one thing about being packed: `isNative()`. Every native
ability sits behind one function in `web/lib/device.js` that has a
browser answer too, so the PWA and the tests never branch on platform.

| Ability | In the iPhone app | In a browser | Milestone |
|---|---|---|---|
| The model's files | fetched from the site with CORS, kept in IndexedDB (the app has no service worker) | as today | N1 |
| Push | the push plugin; token sent to the API | not offered; the switch is hidden | N2 |
| Share the invite link | the share sheet | `navigator.share`, else copy | N3 |
| Contacts (D5) | the contacts plugin | not offered | N3 |
| Haptics | on like, vote, shutter | nothing | N3 |
| A link that opens the app | universal links, then a custom scheme as fallback | the same address opens the site | N4 |
| Sign in with Apple (D1) | through Cognito, in the sign-in sheet that already exists; no new native code | the same | N6 |
| Uploads with the app closed | background `URLSession` | Background Sync on Android | N7 |

Every plugin is an exact pinned version in `native/package.json`, wired
in by `npx cap sync ios`, never by editing the Xcode project by hand
(`native/README.md`). Each new permission needs its sentence in
`Info.plist` and, for App Review, its row in the privacy answers (O16).

**The slow loop.** Nothing native can be tried without a build, Apple's
processing and a phone: 20 to 30 minutes. So: screens stay web and are
proven in `tests/web`; a native milestone is as thin as it can be; the
`simulator` job proves it compiles and starts; and its pull request ends
with the checklist the owner runs once on a phone (O15).

## Tests

- **Every screen has a browser test and a screenshot** (`tests/web`,
  `make screenshots`), at a phone's size, in a light and a dark theme,
  and once in Hebrew for direction. CI keeps them with the run, and a
  pull request that changes a screen shows the new picture.
- **The local app** (`tests/web/localapp.py`, `make local-app`) serves
  both shells, routes `/api/v1/` to the real member handler, runs the
  real events handler on every write to the mocked social table (moto has
  the tables; the harness delivers the stream records itself, in order),
  and replaces exactly three things with fakes: sign-in, the recognition
  model, and Google (a moderation fake that flags any text containing the
  word `flagme` and any photo of the seed's red shapes). Apple is not
  called; pushes are collected in a list the tests read.
- **Races are tested on purpose:** a held-back response for each screen
  that can be left before its data arrives.
- **The desk's tests do not change** except for imports in E0. That they
  keep passing is the proof that the flag-off rule holds.
- **The smoke test** after each staging deploy
  (`scripts/smoke_staging.py`) gains one path once posts exist: an
  encounter, a post, and that post in the feed.

## Accessibility and motion

The prototype already uses real buttons, roles, labels and a
reduced-motion rule; keep all of it. Touch targets at least 44 points.
Text contrast as the prototype's tokens give it, checked by a test over
`tokens.css`. With "reduce motion" on, transitions are fades.

## What is not in this file

The sign-in and first-run screens (G1): not designed. Until they are,
sign-in is today's screen in the new tokens, and first run is: terms,
then the app.
