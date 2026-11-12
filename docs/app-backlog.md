# App backlog

Things decided to leave for later, so they are not lost. Newest first.

## Collection

- **Uploads on an iPhone with the app closed.** Not possible in a PWA:
  Safari has no Background Sync or background fetch, and suspends hidden
  apps. Options if it matters: a native wrapper (Capacitor) using
  `URLSession` background uploads, or smaller files (downscale before
  upload) so the open-app window is enough. *(Raised 2026-10-29.)*
- **An answer with no model guess.** If the model is off or unavailable, the
  result screen asks nothing, because a pick needs the shown guesses. The
  person's "which cat" would still be useful on its own. That needs a pick
  shape without `shown`, and Stats would have to keep those picks apart
  from the product-loop numbers. *(Raised 2026-10-29.)*

- **Confirm the Capture stall's trigger on the phone that hit it.** The 2026-10-29
  fix removes every suspect: no Blob re-write, timeouts, no head-of-line
  blocking. The exact cause on that phone (most likely Safari refusing to
  re-store a Blob read from IndexedDB) was inferred, not observed. If it
  ever recurs, the screen now shows the error: start there. *(Raised 2026-10-29.)*
- **Twelve empty app encounters from before the fix** (`channel = app`,
  `photoCount = 0`, 2026-10-28 and 2026-10-29) are still in the table. The API
  no longer lists them, and new ones are not created. Delete them only if
  Stats starts counting them. *(Raised 2026-10-29.)*
- **Photo counts stored too low before 2026-11-10 stay low** until the next
  write to that cat or encounter (issue #55). Since the fix, each recount adds
  the photos the call itself wrote and leaves out those it removed, so the
  index lagging no longer shortens it. No one-off recount was run; one on
  staging or production needs the owner to ask. *(Raised 2026-11-10.)*
- **"The interface is confusing."** Reported along with the stall; no
  specifics yet. Ask which screens and steps before redesigning anything.
  *(Raised 2026-10-29.)*

- **No way to dismiss a stalled upload.** Stats → Bot health lists records
  still `pending` an hour after they were written. Today an admin can only
  read the list. If it ever grows past a handful, add a "discard" action
  that deletes the record the way Reject does. *(Raised 2026-10-29.)*
- **The bots' flip to `unlabeled` is not conditional on `pending`.** The
  app's `complete` call is, so that a duplicate verdict from the process
  Lambda is never overwritten. The bots write the S3 object and then flip
  unconditionally, so if the process Lambda marks a byte-identical re-send
  `duplicate` in between, the flip undoes it. That needs a sub-second race
  on a duplicate. It has not been seen in the data, but the fix is the same
  `ConditionExpression` the app uses. *(Raised 2026-10-29.)*

## Recognition (phase 1c)

- **Never show a similarity as a percentage.** The morning prototype of
  2026-11-12 showed "92% match"; the same day's redesign shows three
  candidate photos and no numbers, which is right. Kept here so the
  numbers do not come back: the manifest ships `"thresholds": null`
  because right guesses, wrong guesses and never-seen cats overlap.
  `docs/moderation.md`, "The honest-percentage problem". *(Raised and
  resolved in the design 2026-11-12.)*
- **Pairwise verification as a reranker.** Now planned:
  `docs/app-plan/07-rerank.md` (an experiment first, then shadow, then
  live). *(Raised 2026-11-12; planned the same day.)*

- **Mark labels made with the guess in view.** Since 2026-10-29 the admin sees
  the model's guess before labeling. The prediction records when the guess
  was made, but not whether the labeler had seen it. If anchoring ever
  becomes a question (thresholds, fine-tuning), record `shownAt` on the
  prediction when a card or the picker displays it. *(Raised 2026-10-29.)*

- **Thresholds, once the live record earns them.** Today the model only
  ranks. When Stats → Recognition model shows enough labeled guesses that
  the "right first" and "never seen" top scores separate, pick an accept and
  a "new cat" threshold from that record (biased toward "new cat", CLAUDE.md
  "Open-set") and put them in the manifest. *(Raised 2026-10-29.)*
- **Show the top 3 in the picker — later, and on purpose.** Guesses are
  hidden until a session is labeled, so the labels stay unbiased. Revisit
  only once the numbers are good enough that anchoring costs less than it
  saves, and keep a blind sample even then.
- **Videos are not looked at.** A video-only session gets no guess, in the
  desk or in Capture. The
  Spotter page (research/webapp) already pulls frames from a video in the
  browser; the same would work here, with CORS on the raw object.
- **The shared vectors are downloaded whole.** Every phone fetches every
  template (~4 KB each, about 1 MB today) on each refresh. At a few
  thousand photos, fetch only what changed since the last copy, or cap the
  templates per cat, spread across encounters.
- **Shared vectors depend on an admin visiting the Queue.** An admin's
  browser is what embeds new labeled photos and shares them; until one
  does, contributors' phones don't know a newly labeled cat. If that lag
  ever matters, embed in the process Lambda instead (onnxruntime and the
  30 MB model fit there), which is also where the ULID-as-vector-ID of
  CLAUDE.md was always headed.
- **Capture's guess hint is always the same.** "Not sure? A photo of the
  face helps" could become specific once there are thresholds: ask for the
  face only when the top three are close together.
- **Translate the guess card.** It is English, like the rest of Capture.

## The app from the prototype (phase 4)

- **Planned, not built: `docs/app-plan/`.** The owner decided on
  2026-11-12 to build everything the prototype shows, for TestFlight, with
  moderation and re-ranking on Google's Decision 1. The plan holds the
  work in order, the owner's decisions (`DECISIONS.md`) and the owner's
  manual steps (`OWNER_STEPS.md`). The owner answered all 34 decisions
  the same day and postponed production's first promote, so nothing waits:
  the next thing to build is milestone F1. *(2026-11-12.)*
- **The domain is ready to be bought, not bought.** Through AWS, in the
  management account, by `infra/scripts/domain.sh` from a codespace with
  the owner signed in: `docs/MANUAL_STEPS.md`, step 16. The script has
  only ever run against a stand-in for `aws`. *(2026-11-12.)*
- **What the design does not draw yet** is listed once, in
  `docs/app-plan/01-product.md`, "What the design leaves out": sign-in and
  first run, reporting a post, the control that logs a feeding and how a
  feeding spot looks on the map, what replaces "Grade a cat" now that GPA
  is computed, friend requests, an invite code typed by hand, the empty
  and waiting states. *(2026-11-12.)*
- **Left out of the first build on purpose:** the phone number and
  contact matching (D5), Android. *(2026-11-12.)*

## Design

- **A better way out of the full-screen camera.** Today a round ✕ in the top
  corner closes the camera and returns to Capture, with the encounter still
  open. It works, but it is not the most convenient control: it sits far from
  the thumb, and ✕ reads as "cancel", not "step out for a moment". Revisit
  together with the rest of the camera screen. *(Raised 2026-10-28.)*

- **Safari's address bar during sign-in.** An installed iPhone app shows
  Safari's bar and toolbar whenever it is on someone else's address, and
  Google sign-in happens on Google's pages, so the bar appears for those few
  seconds. Sign-out no longer leaves the app, so that is now the only moment
  it shows, and sign-in is rare: a session lasts 30 days. Avoiding it
  entirely would need a native app or a sign-in method of our own.

## Product

- **Translate the app's own screens.** The install page is in Hebrew,
  English, Russian and Arabic; Capture and Cats are still English only. The
  install page quotes the English button names so they match the screen.
- **Remove `?browser`, or keep it.** It opens the app in a browser tab instead
  of the install page, kept as an emergency door in case sign-in fails inside
  the installed app on some phone. Decide once sign-in has been tried on real
  iPhones and Android phones.
