# The work, in order

Each milestone is one branch and one pull request (`README.md`, rule 1).
"Needs" lists what must be true first: decisions (`DECISIONS.md`), owner
steps (`OWNER_STEPS.md`), other milestones. A session that finds a need
unmet says so and stops.

Every milestone also carries, without it being repeated below: tests for
what it adds, the existing tests still green with every flag off,
screenshots for any screen it touches, and the docs it makes true or
false.

## Status

A session ticks its row in the pull request that finishes it.

| ID | Milestone | State |
|---|---|---|
| F1 | The guardrails learn the new shapes | |
| F2 | Shared code, and one catalogue of every key | |
| F3 | The social table, the events Lambda, the seed | |
| F4 | The member API: who you are, flags, who may sign up | |
| B1 | Profiles | |
| B2 | Cats for members, regions | |
| B3 | Posts, the feed, likes | |
| B4 | Name polls | |
| B5 | Friends and invites (B5b: phone and contacts) | |
| B6 | New-cat proposals | |
| B7 | Achievements (B7b: grades, B7c: feedings) | |
| B8 | Reports, blocks, bans, the desk's tools | |
| B9 | Push | |
| B10 | Deleting an account | |
| C1 | Moderation: the client, the policy, shadow runs on text | |
| C2 | Moderation in the desk, and measured | |
| C3 | The blocklist, the gold set, enforce | |
| C4 | Moderation of photos and avatars | |
| R0 | Re-rank: the experiment | |
| R1 | Re-rank: shadow | |
| R2 | Re-rank: measured | |
| R3 | Re-rank: live | |
| E0 | Client groundwork | |
| E1 | The frame: tabs, navigation, themes | |
| E2 | The feed | |
| E3 | The capture flow | |
| E4 | The gallery, a cat's page, the poll | |
| E5 | The map | |
| E6 | Home, profile, settings | |
| E7 | Friends | |
| E8 | Achievements | |
| E9 | The states nobody drew, offline, accessibility | |
| E10 | Languages and right-to-left | |
| N1 | The member app in the iPhone app, with the model | |
| N2 | Push on the phone | |
| N3 | Share, haptics (and contacts) | |
| N4 | Links that open the app | |
| N5 | Permissions, privacy manifest, review readiness | |
| N6 | Sign in with Apple | |
| N7 | Uploads with the app closed | |
| L1 | Gate: internal beta | |
| L2 | Gate: external TestFlight | |
| L3 | Gate: production on | |

## The order

```
O1 decisions ─► O3 first promote ─► F1 ─► (O4) ─► F2 ─► F3 ─► F4
                                                              │
        ┌──────────────────────┬──────────────────────────────┤
        ▼                      ▼                              ▼
   E0 ─► E1              B1  B2 ─► B3 ─► B4               R0 (any time,
        │                          │                      needs only O5, O20)
        ▼                          ▼
   E2 ◄─────────────────────── B3        C1 (as soon as B3 exists)
   E3 ◄── B3, B6                         C2 ─► C3 ─► C4
   E4 ◄── B2, B4
        │
        ▼
   N1 ─► L1 internal beta ─► the rest of B, E, N in any order ─► L2 ─► L3
```

**The first thing a person can hold** is the path
F1–F4 → B2, B3 → E0–E3 → N1: sign in, see a feed, scan a cat, post it,
see it in the feed, on a phone. Everything else widens that. Build that
path first and put it on the owner's phone before building breadth.

Three tracks can run side by side once F4 is in: backend (B), client
(E), and the two Decision 1 tracks (C, R). They meet in the files
`04-api.md` describes, so a route's shape is settled by whichever side
gets there first and recorded there.

---

## Foundations

### F1. The guardrails learn the new shapes

- **Needs:** A1, A2, A3, P2 answered. O3 done.
- **Builds:** only `infra/bootstrap`, `infra/main/allowed-resource-types.txt`
  and their tests. Exactly the list in `02-architecture.md`, "What the
  guardrails must learn". No resource in `infra/main` yet.
- **Done when:** CI's plans for both accounts show no change to
  `infra/main`; a test proves the plan check accepts an event source
  mapping and still refuses, say, `aws_db_instance`; the owner has applied
  bootstrap to **staging**.
- **Owner:** O4, with the full brief. Production's apply can wait until
  F3 has proven staging's.

### F2. Shared code, and one catalogue of every key

- **Needs:** nothing from the owner.
- **Builds:** `src/common/` (caller, responses, table helpers, ULID,
  rate limits, text cleaning); the `Makefile` builds copy it into every
  function's package; `src/admin/` uses it **with no change in
  behaviour**. `docs/data-model.md`: every key of `bgucats-data`, taken
  from spec §6.3, the comment in `dynamodb.tf` and the code, plus the
  social table's catalogue from `03-data-model.md`.
- **Done when:** every existing test passes untouched; both accounts'
  plans show the Lambdas' code changing and nothing else; the zips are
  the same from two builds of the same commit.

### F3. The social table, the events Lambda, the seed

- **Needs:** F1 applied on staging, F2.
- **Builds:** `bgucats-social` with its stream; `bgucats-events` with a
  dispatcher that does nothing yet but log and count, its filter, its
  retry and failure settings, its alarms (errors, iterator age); the
  member-side roles. The local app and the tests learn the second table
  and deliver stream records to the real events handler. The seed gains
  people (extended again by each B milestone).
- **Done when:** a merge deploys it to staging; a row written by hand to
  staging's social table (the owner's session, on request) shows in the
  events Lambda's log; a record made to fail arrives as an alert email
  and does not block the next one.
- **Owner:** the alert email's confirmation, if a new subscription was
  made. Then O4 for production.

### F4. The member API: who you are, flags, who may sign up

- **Needs:** D1, P3. F3.
- **Builds:** `bgucats-app` at `/api/v1/` with its `OPTIONS` route;
  `GET /me` creating the user; `POST /me/terms`; the flags, from
  settings to the response; the three access levels in the existing
  handler and members admitted to the capture routes; the pre-sign-up
  Lambda following `signup_policy` (staging stays `allowlist`);
  `social` off in production. `CLAUDE.md`'s "two roles" becomes three in
  this pull request.
- **Done when:** on staging, a test account signs in, `GET /api/v1/me`
  answers with a user id and flags, and that account can open an
  encounter; a non-admitted address is refused with a clear message; with
  `social` off every `/api/v1/` route is 404 and the desk is unchanged;
  a test on the planned IAM policy proves the member API cannot write
  `bgucats-data`.
- **Owner:** O6 only when production opens (L3).

---

## Backend

Each B milestone: routes in `src/app/` (or `src/admin/` where
`04-api.md` says), handlers in `src/events/` for what follows a write,
the seed extended, `04-api.md` and `docs/data-model.md` corrected to what
was built.

### B1. Profiles

- **Needs:** F4.
- **Builds:** `PATCH /me`, username, avatar upload and confirm, devices
  (stored; nothing sends yet). Display name and avatar are written as
  pending and published by a stub that C1 and C4 replace.
- **Done when:** a second account sees the first one's new name and
  avatar only after the stub passes them; an avatar with an EXIF block is
  refused; another person's email is in no response.

### B2. Cats for members, regions

- **Needs:** F4. O12 for real coordinates (made-up ones are fine until
  then).
- **Builds:** `GET /cats`, `GET /cats/{id}`, cat of the day; the regions
  file and its reader; `bio` and `usualRegionId` on the desk's cat
  editor; the public projection (a test lists every field a member may
  receive, and fails on any other).
- **Done when:** a member's list has no `adminNotes`; the same cat of the
  day for two accounts on one day; a cat's region is its admin-set one,
  else the commonest region among its labeled sessions.
- **Owner:** O13 can start once this is on staging.

### B3. Posts, the feed, likes

- **Needs:** D3. B2.
- **Builds:** `POST /posts`, `GET /posts/{id}`, `DELETE`, like and
  unlike, `GET /feed`, `GET /me/posts`, `GET /cats/{id}/posts`; the pick
  route writing `ENC`; the desk's label routes updating `ENC`; the events
  handlers for a post becoming visible (the cat's counters, `MET`,
  `STATS`); the outbox's `not_ready` contract. Publication goes through
  the same stub as B1.
- **Done when:** in the local app, an encounter posted by one account is
  in a friend's feed with its photos, text and cat; liking twice counts
  once; a hidden post is in no feed and no cat's list; the area shows for
  a friend and not for a stranger; relabeling the session in the desk
  changes the post's cat and the author's "met" counters; the smoke test
  on staging posts and finds it.

### B4. Name polls

- **Needs:** D6. B2.
- **Builds:** names, suggest, vote, take back; the leader kept by the
  events Lambda; the shown-name rule; votes as feed cards; the desk's
  remove-a-name and name-lock.
- **Done when:** the options' votes always sum to the total under
  concurrent votes (a test that votes in parallel); "mango" and
  "Mango " are one option; a pending suggestion is visible to its author
  only; a locked name wins over the poll.

### B5. Friends and invites

- **Needs:** D4. B1.
- **Builds:** invite code and accept; list with period counts and the
  podium; remove; a person's page; requests if D4 says so; mutual-friend
  counts.
- **Done when:** every friend item has its mirror after any sequence of
  accept, remove and block (a property test); an invite between two
  people one of whom blocked the other does nothing and says nothing.
- **B5b, phone and contacts:** only if D5 says so; needs O17 for codes.
  The HMAC lookup, the match route and its tight limit.

### B6. New-cat proposals

- **Needs:** D7. B3.
- **Builds:** `POST /proposals`; the desk's Proposals queue with approve
  (creates the cat through the existing create, labels the session) and
  merge (labels it as an existing cat); `ENC`, the post and the proposer's
  counters following the decision; the name idea entering the new cat's
  poll.
- **Done when:** a proposed cat is not in `GET /cats` until approved; a
  merged proposal's post shows the existing cat; the dataset table's
  session is labeled by the desk route and by nothing else.

### B7. Achievements

- **Needs:** D8, D11. B3, B4.
- **Builds:** the rules as one data file; points, levels, badges by the
  events Lambda; `GET /achievements`; a recount script per counter.
- **Done when:** replaying the same stream records twice changes
  nothing; a relabel takes back exactly what the claim gave; the recount
  script's result equals the stored counters on the seeded campus.
- **B7b, grades / B7c, feedings:** only when D9 / D10 are answered and
  designed.

### B8. Reports, blocks, bans, the desk's tools

- **Needs:** D15. B3, B5.
- **Builds:** `POST /reports`, blocks; the email per report; hiding at
  the threshold; the desk's Reports queue, People list, ban, hide,
  remove.
- **Done when:** two people who blocked each other see nothing of each
  other in the feed, the polls' friend marks, the podium or search; a
  banned account's every write is refused by both APIs; three reports
  hide a post and one admin action restores it.

### B9. Push

- **Needs:** D18, A5. B3, B5. O7 before it can be tried on a phone.
- **Builds:** the sender in the events Lambda (token-signed requests to
  Apple, the right environment, dead tokens removed on Apple's answer),
  the triggers, the per-person daily cap, the `push` flag.
- **Done when:** in tests, the collected pushes for a seeded day are
  exactly the expected ones and carry no user-written text.

### B10. Deleting an account

- **Needs:** D14. Everything above that stores something about a person.
- **Builds:** `DELETE /me` and the deletion job
  (`03-data-model.md`).
- **Done when:** after deleting a seeded account that had done
  everything, a scan of the social table finds its user id nowhere, the
  counters it touched are what a recount gives, and its photos are where
  D14 says; running the job twice, or stopping it half-way and running it
  again, ends the same.

---

## Moderation

### C1. The client, the policy, shadow runs on text

- **Needs:** M1. O5 (a staging key). B3 or B4 (something to check).
- **Builds:** `src/common/decisions.py`; the policy file and its
  validation; the text kinds wired into the events Lambda, replacing the
  stub; runs recorded; `moderation_mode` and `hold_unchecked`; the daily
  ceiling; the secret's name in `set-secret.sh`. **First task:** one real
  request from a codespace with the owner's key, to confirm the API's
  shape, the yes/no type's identifier and whether WebP is accepted;
  correct `06-moderation.md` with what was found and the date.
- **Done when:** on staging in shadow, a seeded post's text has a run
  with probabilities; with the key removed, items wait and the queue says
  why; no test touches the network.

### C2. In the desk, and measured

- **Needs:** C1.
- **Builds:** the Moderation tab, resolve and run-again, the measured
  table under Stats.
- **Done when:** approving and rejecting in the desk publishes and
  refuses, and each decision appears in the measured table against the
  model's outcome.

### C3. The blocklist, the gold set, enforce

- **Needs:** M2, M3. O11. C2.
- **Builds:** the blocklist check in the API; `scripts/moderation_eval.py`;
  the enforce path; per-script exemption when a language misses the bar.
- **Done when:** the eval's table exists for the owner's gold set; the
  pull request that would set `enforce` anywhere shows the evidence
  `06-moderation.md` asks for. This milestone builds the switch; it does
  not flip it.

### C4. Photos and avatars

- **Needs:** M4. C1.
- **Builds:** the photo and avatar kinds; a post visible only when its
  text and every photo passed; the desk's queue showing the photo; the
  welfare mark on `graphic` and `animal_harm`.
- **Done when:** in the local app, a post whose photo the fake flags
  stays hidden with its text passed; a photo used by two posts is checked
  once.

---

## Re-ranking

### R0. The experiment

- **Needs:** O5 (a research key), O20. M1 (the same disclosure).
  Independent of every other milestone.
- **Builds:** `research/catreid/pairwise.py`, its tests with faked
  responses, round 4 of `research/FINDINGS.md`.
- **Done when:** the findings hold the tables `07-rerank.md` lists,
  including the controls and the sentence about what 13 sessions can and
  cannot show.

### R1. Shadow

- **Needs:** R0's findings read by the owner and a go. C1 (the shared
  client). B3 (`ENC` and members on the capture routes).
- **Builds:** the route, the record, the version hash, the outbox step,
  `rerank_mode`.
- **Done when:** on staging, a posted encounter has a `RERANK` item;
  a labeled session is refused; over the ceiling nothing is sent.

### R2. Measured

- **Needs:** R1.
- **Builds:** the side-by-side table in Stats, through `summarize`.

### R3. Live

- **Needs:** K1, K2 met and shown. R2. E3.
- **Builds:** the small query copy, the 2.5-second rule, the source
  recorded on the pick.
- **Done when:** with the network held back in a test, the candidates
  appear at 2.5 seconds in the embedding's order and never move.

---

## Client

Each E milestone ports its screens from the frozen prototype, in every
theme, flowing at three widths, direction-neutral, with strings in the
English file.

### E0. Client groundwork

- **Needs:** A4. O2.
- **Builds:** the frozen prototype under `docs/design/prototype/`;
  `web/lib/` moved out of `app.js` with the desk unchanged; `tokens.css`
  with four themes; the vendored renderer and font with checksum tests;
  the `t()` function and `en.json`; the lint for physical CSS properties;
  `app.html` showing an empty frame; the `frontDoor` setting; the local
  app serving both shells and `/api/v1/`.
- **Done when:** the desk's tests pass with only their imports changed;
  `app.html` opens signed-in in the local app.

### E1. The frame

- **Needs:** E0, F4.
- **Builds:** the tab bar with its lens and its shrink on scroll, page
  slides and edge swipes, the glass button, menus, sheets, the confirm
  dialog, the toast, theme switching, the store.
- **Done when:** screenshots of the frame in four themes; "reduce
  motion" turns slides into fades.

### E2. The feed

- **Needs:** E1, B3 (B4 for vote cards).
- **Builds:** post cards, several photos, like, the photo's menu, cat of
  the day, paging, the top buttons.

### E3. The capture flow

- **Needs:** E1, B3, B6. D13 for the location words.
- **Builds:** the camera, the four pages, both entries (scan and "+"),
  every ending in `01-product.md`'s table, on the outbox; the result
  surviving a reload.
- **Done when:** the six endings each write exactly what the table says
  (a test per ending against the local app); with the network off, an
  encounter is posted and everything arrives when it returns; the pick's
  record is what today's Capture writes.

### E4. The gallery, a cat's page, the poll

- **Needs:** E1, B2, B4.

### E5. The map

- **Needs:** E4. O12 for it to be right.
- **Builds:** the drawn campus from the regions file and the prototype's
  shapes, dragging, the habitat sheet.

### E6. Home, profile, settings

- **Needs:** E1, B1 (B7 for the cards' numbers, B10 for delete).

### E7. Friends

- **Needs:** E6, B5 (B8 for block and report).

### E8. Achievements

- **Needs:** E6, B7.

### E9. The states nobody drew, offline, accessibility

- **Needs:** the screens above.
- **Builds:** every row of "States the design does not draw"
  (`05-client.md`), with a screenshot of each for the owner; the contrast
  test; touch-target sizes.

### E10. Languages and right-to-left

- **Needs:** D17. E9. O14 before a language is offered.
- **Builds:** `he.json`, `ru.json`, `ar.json` as drafts; the language
  menu; a Hebrew and an Arabic screenshot of every screen.

---

## The iPhone app

Each N milestone ends with the owner's phone checklist (O15) and says
which parts no person has run.

### N1. The member app in the iPhone app, with the model

- **Needs:** E3.
- **Builds:** the bundle's `frontDoor`; the model's files reachable from
  the app's origin (CORS on that path through an AWS-managed response
  policy, so no new resource type) and kept in IndexedDB; this closes
  item 3 of `docs/ROADMAP.md`, 2e.
- **Done when:** the simulator job starts on the feed; on the owner's
  phone, a scan offers three candidates.

### N2. Push on the phone

- **Needs:** B9, O7.

### N3. Share, haptics (and contacts)

- **Needs:** E7. Contacts only with B5b.

### N4. Links that open the app

- **Needs:** A6; O9 if a domain. B5.
- **Builds:** the invite landing page on the site; universal links (or
  the custom scheme until there is a domain); accepting an invite on
  open; the manual code field once G8 is designed.

### N5. Permissions, privacy manifest, review readiness

- **Needs:** the features that ask for permissions.
- **Builds:** each permission's sentence in every offered language; the
  privacy manifest; the table of collected data for O16, generated from
  the code and checked by a test so it cannot drift.

### N6. Sign in with Apple

- **Needs:** D1 says so. O8.

### N7. Uploads with the app closed

- **Needs:** N1. Already in `docs/app-backlog.md`.

---

## Gates

A gate is a checklist the owner signs, not code. The session that
prepares one writes the evidence for each line.

### L1. Internal beta

The people are known to the owner; nothing is public.

- The first-thing-to-hold path works on the owner's phone.
- `moderation_mode = shadow`, `hold_unchecked` off, on staging.
- Every tester is in the App Store Connect team and on staging's
  allowlist.
- A draft privacy page exists (O10).
- Staging holds only made-up or testers' own content. **Real contributor
  photos never go to staging** (`docs/ROADMAP.md`, "Never"); testers'
  posts there are test content and are not the dataset.

### L2. External TestFlight

Strangers. Apple reviews the build.

- B8 and B10 are built and in the design: report a post, block, delete
  account (G2–G4 closed).
- C2 at least; `hold_unchecked` on.
- O10 final, O16 done, D16 answered; D1's Apple question answered and N6
  if so.
- O19: who reads the queues daily.
- N5.
- A month's cost so far, against P1.
- The app points at the account the owner chooses. If that is
  production, L3 comes first.

### L3. Production on

- The plan for production shows what staging has run.
- O4, O5, O7 done for production; O6.
- `social` on, `frontDoor = app`, by pull requests, promoted by tag.
- The existing collaborators can still do everything they did.
- Rollback is the flag, then `git revert`.

## After this plan

Android; grades and feedings once designed; live update of `web/` in the
iPhone app; CloudFront for photos if the bill asks; thresholds for the
recognition model when the live record earns them.
