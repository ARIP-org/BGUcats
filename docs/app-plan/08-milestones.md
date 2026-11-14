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
| F1 | The guardrails learn the new shapes | built 2026-11-12; **applied on staging 2026-11-12** and proven (`docs/MANUAL_STEPS.md`, step 17); production with its first promote |
| F2 | Shared code, and one catalogue of every key | merged 2026-11-12 |
| F3 | The social table, the events Lambda, the seed | merged 2026-11-12. The local app and the seed learn the table in B3c |
| F4 | The member API: who you are, flags, who may sign up | merged 2026-11-12 |
| B1 | Profiles | B1a (name, settings), B1b (photo) and B1c (username) merged 2026-11-13; devices wait for B9 |
| B2 | Cats for members, regions | merged 2026-11-12 |
| B3 | Posts, the feed, likes | merged 2026-11-12 (B3a, B3b, B3c); the smoke test posts on staging since step 18 |
| B4 | Name polls | merged 2026-11-13 (B4a: names, votes, the leader; B4b: the desk's remove and lock). Votes as feed cards moved to B5: a vote card is friends' votes |
| B5 | Friends and invites (B5b: phone and contacts) | B5a (invite links, the list, a person's page, friends and their name votes in the feed) merged 2026-11-13; blocks with B8; mutual counts merged 2026-11-14 |
| B6 | New-cat proposals | merged 2026-11-12 |
| B7 | Achievements (B7b: GPA, computed; B7c: feedings) | B7a (points, levels, six badges) and B7b (the grade) merged 2026-11-13; B7c (feedings, behind the `feeding` flag) and the recount script merged 2026-11-14 |
| B8 | Reports, blocks, bans, the desk's tools | merged 2026-11-13 (B8a blocks, B8b reports, B8c bans) |
| B9 | Push | built 2026-11-14, in review: the device routes, the four notifications, the cap, the sender. Sends nothing until a phone registers (N2) and Apple's key is set (O7) |
| B10 | Deleting an account | |
| C1 | Moderation: the client, the policy, shadow runs on text | |
| C2 | Moderation in the desk, and measured | |
| C3 | The blocklist, the gold set, enforce | |
| C4 | Moderation of photos and avatars | |
| R0 | Re-rank: the experiment | |
| R1 | Re-rank: shadow | |
| R2 | Re-rank: measured | |
| R3 | Re-rank: live | |
| E0 | Client groundwork | merged 2026-11-12 |
| E1 | The frame: tabs, navigation, themes | merged 2026-11-12 |
| E2 | The feed | merged 2026-11-12 |
| E3 | The capture flow | merged 2026-11-12; every page drawn as the prototype draws it, merged 2026-11-14 |
| E4 | The gallery, a cat's page, the poll | E4a (gallery and cat page) merged 2026-11-13; the poll on the cat's page merged the same day with B4a |
| E5 | The map | E5a (the drawn campus, dragging, the habitats and their sheet) merged 2026-11-13; feeding spots wait for the design (G6), the real places for O12 |
| E6 | Home, profile, settings | E6a (the screens) merged 2026-11-13; the name is edited since B1a, the photo since B1b |
| E7 | Friends | E7a (Home's card, the friends page, the invite, a person's page) merged 2026-11-13 with B5a; Block in a friend's menu since B8a, Report since B8b |
| E8 | Achievements | E8a (Home's card and the sheet) merged 2026-11-13 with B7a; "Cats fed", Snack Giver and "Feed a cat" with B7c |
| E9 | The states nobody drew, offline, accessibility | merged 2026-11-14: the missing states, the contrast test, the touch-target test |
| E10 | Languages and right-to-left | merged 2026-11-14 as drafts: Hebrew, Russian and Arabic, the language menu, every screen checked from the right. Offered in staging only until a speaker has read them (O14) |
| N1 | The member app in the iPhone app, with the model | merged 2026-11-13; on the owner's phone once the API answered its preflight (the same day) |
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
O1 decisions (done) ─► F1 ─► (O4, staging) ─► F2 ─► F3 ─► F4
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

- **Needs:** nothing. A1, A2, A3 and P2 are answered (2026-11-12), and
  the first production promote (O3) was postponed by the owner and no
  longer comes first. **This is the next thing to build.**
- **Builds:** only `infra/bootstrap`, the plan check and their tests.
  Exactly the list in `02-architecture.md`, "What the guardrails must
  learn". No resource in `infra/main` yet, and so not the allowlist line
  either (it comes with the resource, in F3).
- **Done when:** CI's plans for both accounts show no change to
  `infra/main`; `terraform -chdir=infra/bootstrap test` passes in CI; the
  plan check refuses a mapping with provisioned pollers and still refuses,
  say, `aws_db_instance`; the owner has applied bootstrap to **staging**
  and the simulator answers in `docs/MANUAL_STEPS.md`, step 17, are as
  expected.
- **State, 2026-11-12:** built and tested on the branch. Waiting for the
  owner's staging apply (step 17).
- **Owner:** O4 for **staging**, with the full brief. Production's apply
  waits for production's first promote (P2, O3) and must come before it.

### F2. Shared code, and one catalogue of every key

- **Needs:** nothing from the owner.
- **Builds:** `src/common/` (caller, responses, table helpers, ULID,
  rate limits, text cleaning); the `Makefile` copies it into the
  functions that import it, today only the admin API; `src/admin/` uses
  it **with no change in behaviour**. `docs/data-model.md`: every key of
  `bgucats-data`, from the code, with a test that fails on a key it does
  not name. The social table's keys join it in F3, when the table exists.
- **Done when:** every existing test passes untouched; both accounts'
  plans show the admin Lambdas' code changing and nothing else; the zips
  are the same from two builds of the same commit.
- **State, 2026-11-12:** built. The admin tests passed unchanged (150);
  two builds of the admin package were byte-identical, and differ from
  the one before only in `handler.py` and the new `common/`. The plans
  are CI's, on the pull request.

### F3. The social table, the events Lambda, the seed

- **Needs:** F1 applied on staging, F2.
- **Builds:** `aws_lambda_event_source_mapping` onto
  `infra/main/allowed-resource-types.txt` (A3 decided it; the line is
  added with the first resource of its kind); `bgucats-social` with its
  stream; `bgucats-events` with a
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
  made.
- **State, 2026-11-12:** built: the table with its stream, the events
  Lambda (sorts changes by kind, logs one line per batch, reports a failed
  record alone), its role, the stream mapping with its filter, the
  failure path to the alerts topic, two alarms. The filter is a file
  (`src/events/filters.json`) with a test that every kind the handler
  knows reaches it and that nothing it writes does (the guard against the
  Lambda starting itself in a loop). Tested against records from a real
  DynamoDB stream in moto. **Moved to B1:** the local app's second table
  and the seed's people, because nothing writes the table until B1, so
  there is nothing yet for either to show.

### F4. The member API: who you are, flags, who may sign up

- **Needs:** D1, P3. F3.
- **Builds:** `bgucats-app` at `/api/v1/` with its `OPTIONS` route;
  `GET /me` creating the user; `POST /me/terms`; the flags, from
  settings to the response; two roles, `user` and `admin` (R1:
  `collaborator` is read as `user`), and every user admitted to the
  capture routes; the pre-sign-up Lambda following `signup_policy`
  (staging stays `allowlist`); `social` off in production. `CLAUDE.md`'s
  "two roles on the one allowlist item" is rewritten as user and admin in
  this pull request.
- **Done when:** on staging, a test account signs in, `GET /api/v1/me`
  answers with a user id and flags, and that account can open an
  encounter; a non-admitted address is refused with a clear message; with
  `social` off every `/api/v1/` route is 404 and the desk is unchanged;
  a test on the planned IAM policy proves the member API cannot write
  `bgucats-data`.
- **Owner:** O6 only when production opens (L3).
- **State, 2026-11-12:** built. `src/app/` behind `ANY /api/v1/{proxy+}`
  and its `OPTIONS` route, with `GET /me` (makes the account in one
  conditional transaction: the sign-in lookup, the user, the username,
  the invite code) and `POST /me/terms`; `src/common/admission.py` for
  both roles and the three policies, used by the sign-up trigger and
  both APIs on every call; the desk's people screen says "user"; the
  CORS configuration allows `PUT` for the likes and votes to come.
  `social` is on in staging, off in production. Tested with moto and the
  screen tests; the read-only rule on the dataset is a test over the
  Terraform. Not tried by a person: signing in on staging and calling
  `/api/v1/me`, which needs the member client (E0) or a token by hand.

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
- **B1a, built 2026-11-13:** `PATCH /me`. A display name is written
  beside the published one (`pendingName`) and moved over by the events
  Lambda (`publish_name`, where moderation goes, C1), on the condition
  that it is still the name that was read. Language, theme and
  notifications are stored as sent. On the profile the name is edited in
  its row and saved on "done"; the theme chosen there follows the account
  to the next phone.
- **B1b, built 2026-11-13:** the profile photo. The phone cuts it
  square, scales it to 512 px and re-encodes it (`web/social/avatar.js`),
  which drops the camera's metadata; the API signs an upload pinned to
  `avatars/{userId}/{avatarId}.jpg`, checks the file's own bytes on
  confirm and refuses one that still carries EXIF, XMP or IPTC
  (`jpeg_problem` in `src/common/media.py`). It waits as
  `pendingAvatarKey` and the events Lambda publishes it, as a name. The
  member API's role gains `avatars/*` in the media bucket and nothing
  else there. A replaced photo is removed at the person's next change:
  the events Lambda has no access to the bucket.
- **B1c, built 2026-11-13:** `PUT /me/username`, the transaction of
  `03-data-model.md`, and a Username row on the profile beside the name
  (the prototype shows the username and draws no way to change it; G16's
  first-run choice is not built). Not held for a check as a display name
  is: a lookup key cannot be pending. Still to build: devices, with push
  (B9).

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
- **State, 2026-11-12:** built: `GET /api/v1/cats` and
  `GET /api/v1/cats/{id}` (shown name and its source, cover and newest
  photos, counters from the social table, cat of the day by Israel date),
  `web/regions.json` (placeholders, O12) read by both the phone and the
  API through `src/common/regions.py`, the desk's **Public info** on a
  cat (a description and the usual place). The public projection is a
  test that lists every key. **Not built, on purpose:** a cat's region
  falling back to the commonest region of its labeled sessions. It would
  cost a query per cat per list; it belongs with the events Lambda's
  counters (B7). Until then the region is the admin's or none.

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
- **Split in two (2026-11-12), to keep each pull request readable:**
  - **B3a, built:** `POST /posts` (the encounter must be the author's,
    every photo in it and confirmed, 425 `not_ready` otherwise; text
    cleaned; the area from the encounter's own location, kept only if
    shared; one post id is one post, however often it is sent; 20 a
    day), `GET /posts/{id}`, `DELETE /posts/{id}`, like and unlike (one
    transaction each, counted once), `GET /feed` (newest first, month by
    month, a cursor), `GET /me/posts`, `GET /cats/{id}/posts`. The events
    Lambda publishes a new post at once and counts it on its cat, one
    conditional transaction, so a second delivery does nothing: the
    stand-in for moderation, which C1 replaces. Until there are friends
    (B5) the area is shown to the post's author only.
  - **B3b, built:** `ENC` written by the pick and by `POST /posts`, and
    kept on the label by the desk's assign, unassign, merge and reject
    (`src/common/encounters.py`); the events Lambda recounting the
    person's `MET` and `STATS` from all their encounters on every change,
    and moving a post to the label's cat with its likes, or removing it
    if the encounter was rejected; one post per encounter; `counters` on
    `GET /me` and `met` on a cat's page; likes conditional on the post's
    cat, so a like and a correction never count on two cats. The desk's
    role may get and update `IDENTITY#…` and `USER#…` items in the app's
    table and nothing else there. Found on the way: the member API
    shipped without `tzdata` (fixed in its own pull request first).
    **Not built, on purpose:** points and a cat's popularity (B7, from the
    same `ENC` items); an encounter made before its person first opened
    the app is never counted.
  - **B3c, built:** the local app (`tests/web/localapp.py`) runs the
    member API and the events Lambda too: the second table, `/api/v1/`
    routed to `app.handler`, `PUT`, and every write followed by the
    stream stand-in (`tests/events/stream.py`). The seed (`Campus`) learns
    `join`, `pick`, `post` and `like`; `small()` has the collaborator's
    post, liked by the admin; `full()` adds three made-up people who each
    meet a cat, post it and like the others' posts, topped up like the
    rest. `staging_api` sends `/api/v1/` to `bgucats-app`. The smoke test
    gains step 6 (post, published, in the feed) and its step 7 checks the
    post is gone with its encounter. **Needs the owner first:**
    `docs/MANUAL_STEPS.md` step 18, the smoke role invoking `bgucats-app`
    on staging. **Not done:** friends (B5), so "a friend's feed" is
    everyone's feed until then.

### B4. Name polls

- **Needs:** D6. B2.
- **Builds:** names, suggest, vote, take back; the leader kept by the
  events Lambda; the shown-name rule; votes as feed cards; the desk's
  remove-a-name and name-lock.
- **Done when:** the options' votes always sum to the total under
  concurrent votes (a test that votes in parallel); "mango" and
  "Mango " are one option; a pending suggestion is visible to its author
  only; a locked name wins over the poll.
- **B4a, built 2026-11-13:** the four member routes (`04-api.md`), the
  options and votes as `docs/data-model.md` has them, and in the events
  Lambda the step that makes a pending name live (`publish_suggestion`,
  where moderation goes, C1) and the leader (`lead`). A vote is one
  transaction, conditional on the vote item and on each option's status
  as read, so two taps count once and a name going live under a vote is
  counted once; `tests/app/test_polls.py` drives those two races by
  hand and checks after every move that the total is the votes on live
  options and each count is the votes that name it. Threads against the
  mocked table would prove nothing about DynamoDB. **Mine, not the
  plan's:** the admins' own name stands in the poll from the start with
  no votes, so it can be voted to stay.
- **B4b, built 2026-11-13:** the desk's half. On a cat's page in the
  desk, "Name poll": what the app calls the cat and why, every suggested
  name with its votes and author, **Remove** on each and **Lock the
  name**. The desk's API only marks (`removed` on the option,
  `lockedName` on the cat's public item): its role gained the `CAT#`
  partition of the app's table and no new action. What follows from a
  removal is the events Lambda's (`remove_name`): the count to zero and
  off the total in one transaction, then the votes that named it
  deleted. A vote that leaves a removed name does not touch its count
  (`_move_vote`), or the total would lose that vote twice;
  `tests/app/test_polls_desk.py` drives that race. A removed name stays
  out. **Not built:** restoring a removed name. The admins' own name is
  listed, and removable, only once somebody has voted for it; until
  then it is not an item.
- **Moved to B5:** votes as feed cards. A vote card is "Daniel and Noa
  voted…": friends' votes, and there are no friends before B5. The
  `VOTE` item gets its `FEED#` keys there.

### B5. Friends and invites

- **Needs:** D4. B1.
- **Builds:** invite code and accept; list with period counts and the
  podium; remove; a person's page; requests if D4 says so; mutual-friend
  counts; friends' name votes as feed cards (from B4).
- **Done when:** every friend item has its mirror after any sequence of
  accept, remove and block (a property test); an invite between two
  people one of whom blocked the other does nothing and says nothing.
- **B5a, built 2026-11-13:** D4 as answered: an invite link makes two
  people friends at once, and there is nothing else yet (D5: no contacts
  in the first build), so no requests. `POST /invites/{code}/accept`
  writes both `FRIEND` items in one transaction that also checks no
  `BLOCK` stands between the two (blocks arrive with B8; the check is
  already there and tested); `DELETE /friends/{id}` deletes both in one.
  `GET /friends` is the caller and their friends by cats found, this
  month or in all; `GET /users/{id}` and `…/posts` are a person's page.
  In the feed an author is marked as a friend, and a friend sees a
  post's area (D3). `tests/app/test_friends.py`: the mirror after 120
  random accepts and removes among three people, a block either way,
  every key a person is sent.
- **Friends' name votes in the feed** (from B4, with B5a): a `VOTE`
  item carries `FEED#` keys, and `GET /feed` folds friends' votes into
  one card per cat (`_vote_card`), built from the poll as it is now. A
  pending name makes no card; a vote taken back or a friend removed
  takes the card away; the cursor carries the cats already shown. In
  the app (`VoteCard` in `web/social/feed.js`) a tap on a name votes,
  as on the cat's page.
- **Mutual-friend counts, built 2026-11-13:** `GET /users/{id}` carries
  `mutual`, how many friends the caller and that person have in common
  (never who; null on one's own page), and the person's page says it.
- **Not built:** the "friend" events (a push, B9).
- **B5b, phone and contacts:** only if D5 says so; needs O17 for codes.
  The HMAC lookup, the match route and its tight limit.

### B6. New-cat proposals

- **Needs:** B3. D7 is answered: nothing about a new cat is public until
  an admin approves. Its open half (does the form keep "& create a
  post"?) does not block the backend; the held post is built either way.
- **Builds:** `POST /proposals`; the desk's Proposals queue with approve
  (creates the cat through the existing create, labels the session),
  merge (labels it as an existing cat) and reject; a post that names an
  open proposal held, then published under the decided cat or left
  unpublished; `ENC` and the proposer's counters following the decision;
  the name idea entering the new cat's poll.
- **Done when:** a proposed cat is in no member's `GET /cats`, feed or
  map until approved; its post is seen by its author only, with the
  waiting state, and by a friend only after approval or merge; a merged
  proposal's post shows the existing cat; a rejected one's post is never
  published; the dataset table's session is labeled by the desk route and
  by nothing else.
- **Built (2026-11-12):** `POST /api/v1/proposals` and
  `GET /api/v1/me/proposals`; posts that claim `{proposalId}`, held while
  it is open (the author sees the post pending, with the proposal); the
  pick's `new`; the desk's routes and, at the top of the Queue, the
  proposals with "Add as a new cat", "It's a cat we know…" and "Not a new
  cat". An approved proposal's id is the new cat's id, so a retried
  approve makes one cat; its coat and usual place come from the proposal.
  The events Lambda releases the waiting post under the decided cat, or
  hides it on reject (`decide_proposal`, `release`). The desk's role may
  now query `PROPOSALS#…` on `GSI2` and get and update `PROPOSAL#…`.
  **Not built, on purpose:** the name idea entering the cat's poll
  (polls are B4); a session labeled straight from the Queue while its
  proposal is still open leaves the proposal open and its post waiting
  (decide the proposal instead).

### B7. Achievements

- **Needs:** D8, D11. B3, B4.
- **Builds:** the rules as one data file; points, levels, badges by the
  events Lambda; `GET /achievements`; a recount script per counter.
- **Done when:** replaying the same stream records twice changes
  nothing; a relabel takes back exactly what the claim gave; the recount
  script's result equals the stored counters on the seeded campus.
- **B7a, built 2026-11-13:** the rules are `web/achievements.json`,
  packed with both Lambdas (`common/achievements.py`; the events Lambda
  reads its own copy). On every change to one of a person's encounters
  the events Lambda works out again, from all of them: `points` and
  `posts` on `STATS#ALL`, and the badges an encounter can give (First
  Meow, Night Owl, Explorer, Cat Whisperer), given or taken back to
  match. An encounter now keeps the `hour` it began at. Name Giver is
  given when a suggested name leads (`lead`) and kept. Dean's List is
  not stored: `GET /achievements` asks it of the cats' grades as they
  stand. `tests/app/test_achievements.py` compares the points with a
  recount after every step.
  - **Mine, for the owner to change in the file:** the levels' starts
    (0, 50, 200, 500, 1,500, 3,000: the prototype's "Level 4 · 1,240 ·
    260 to Level 5" and its bar fit 500 and 1,500) and the names of
    every level but "Campus Scout" (`web/i18n/en.json`, `level.N`).
  - **Left out:** Snack Giver, "Cats fed" and "Feed a cat +10" until
    feedings (B7c). Critic, "Cats graded" and "Grade a cat +1" have no
    meaning since D9; the plan's proposal ("Names voted", "+1 for a
    vote") is not built until confirmed, and the tiles show encounters
    and posts instead. The recount as a script.
- **B7b, GPA** (D9, answered: computed, nobody grades): the per-month
  popularity counter on each cat, kept and corrected with the same
  bookkeeping as "met"; the grade worked out in `GET /cats`; the `gpa`
  flag. **Done when:** the most popular seeded cat reads 4.0, a cat with
  no encounter in three months reads null, and relabeling an encounter
  moves both cats' grades by exactly what a recount gives.
- **B7b, built 2026-11-13:** the events Lambda keeps, per person, what
  they give each cat a month (`METM#`), and moves the cat's
  `pop{yyyy-mm}` by the difference in one transaction
  (`count_popularity`), so a record seen twice changes nothing.
  `GET /cats` and `GET /cats/{id}` carry `gpa` (`grades`); the `gpa`
  flag is on in both accounts' settings and hides it everywhere when
  off. In the app: the chip beside a cat's name, a dash for a cat nobody
  met lately, and "Highest GPA", the gallery's first sort and the one it
  opens with. `tests/app/test_gpa.py` compares the stored numbers with a
  recount from the encounters after every step. **Not built:** the
  recount as a script (with B7), the map's habitat sheet (E5).
- **B7c, feedings** (D10, answered: build it): the feeding route and its
  limits, `lastFedAt`, points for two a day, the desk's remove, the
  feeding spots in the regions file. **Needs** O12 for the real spots
  (made-up ones until then). **Done when:** a second log for the same cat
  inside four hours is refused; a third feeding in a day earns nothing;
  removing the newest feeding puts "last fed" back to the one before.
  The screens for it wait for the design (G6).
- **B7c, built 2026-11-13**, behind the `feeding` flag (on in both
  accounts' settings; off, the route is 404 and nothing of it shows).
  `POST /cats/{id}/feedings` writes the feeding under the cat and a copy
  under the person in one transaction with `FEDCAT#{catId}`, a pointer
  whose write condition is the four-hour rule; six a day by the shared
  limiter. The events Lambda (`count_feeding`) reads the cat's newest
  feeding that stands into `lastFedAt`, and works the person's
  `fedPoints`, `catsFed` and Snack Giver out again from their copies
  (`fed`), so a record seen twice changes nothing. Points shown are the
  encounters' plus the feedings'. The desk's cat page lists a cat's
  feedings with **Remove**, which only marks. The rules file has
  `points.feed`, `feedingsCountedADay` and the badge; `web/regions.json`
  has three made-up feeding spots until the owner's list (O12).
  `tests/app/test_feedings.py` covers the three "done when" and the
  flag. In the app (G6, drawn like the other cards): the card on a cat's
  page and its sheet (`web/social/feeding.js`); "Cats fed", Snack Giver
  and "Feed a cat +10" in Achievements. **Not built:** feeding spots on
  the map (their look is the designer's); reporting a single feeding
  (nobody sees one to report: the cat's page shows only the last time).
- **The recount, built 2026-11-13:** `scripts/recount.py` reads the
  app's table once and works every stored sum out again with the events
  Lambda's own functions: a person's encounters, cats met, points,
  posts, badges and feeding numbers, what they give each cat's
  popularity, each cat's `pop{yyyy-mm}` and "last fed". One line per
  difference; it only reads (`docs/deploy.md`, "Post-deploy checks").
  `tests/app/test_recount.py`: nothing differs after meeting, posting,
  feeding, relabeling and removing; a counter changed by hand is named.

### B8. Reports, blocks, bans, the desk's tools

- **Needs:** D15. B3, B5.
- **Builds:** `POST /reports`, blocks; the email per report; hiding at
  the threshold; the desk's Reports queue, People list, ban, hide,
  remove.
- **Done when:** two people who blocked each other see nothing of each
  other in the feed, the polls' friend marks, the podium or search; a
  banned account's every write is refused by both APIs; three reports
  hide a post and one admin action restores it.
- **B8a, built 2026-11-13:** blocks. `PUT` and `DELETE /blocks/{id}`,
  `GET /blocks`; a block is `BLOCK#` under the one who blocked and
  `BLOCKEDBY#` under the other, written with the end of the friendship
  in one transaction. `_hidden(me)` is everyone a block keeps the
  caller apart from, either way; the feed, a cat's posts, a post by its
  id and a person's page leave them out, with the answer nobody gets.
  `tests/app/test_blocks.py` runs 160 random accepts, removes, blocks
  and unblocks among three people and checks every mirror, and that
  nobody is a friend of someone a block keeps them from. In the app:
  **Block** in a friend's menu (as drawn) and in a menu on anyone's
  page; the posts of someone just blocked leave the feed on screen.
  - **Mine (G4, "there is no list to unblock from"):** "Blocked people"
    in the profile, with **Unblock**.
- **B8b, built 2026-11-13:** reports.
  - `POST /api/v1/reports` writes the report and one item per person per
    thing in one transaction, and always answers the same.
  - The events Lambda (`take_report`) emails the admins through the
    alerts topic, once per report, with the reason and the count and
    nothing a person typed; and hides a post that three different
    people reported (`REPORT_HIDE_AT`, held to `common/reports.py` by a
    test).
  - An admin's decision about a post is a mark on it (`modAction`) that
    the events Lambda carries out (`set_post`): state, feed and cat
    keys, and the cat's counters in one transaction, so hiding and
    putting back are exact opposites, likes included.
  - The desk: "Reported" at the top of the Queue, one card per thing,
    with **Leave it** (or **Put it back** for a post the reports hid),
    **Hide post**, **Remove post**, **Remove name**. Its role gained
    three partitions (`REPORT#`, `REPORTS#`, `POST#`) and no action.
  - The app (`web/social/report.js`): **Report** in someone else's
    photo menu, in a friend's menu (as drawn) and on a person's page; a
    sheet with six reasons and an optional line; "Thank you. Someone
    looks at every report within a day."
  - **Mine, for the owner (D15):** the six reasons and the sheet, which
    the design does not have; three reporters to hide a post (the
    plan's recommendation).
  - **Not built:** reporting a name from the app (the route takes
    it); showing an admin the reported profile photo.
- **B8c, built 2026-11-13:** bans. `POST /api/people/{id}/ban` and
  `/unban` mark the person; `ban` is also an answer to a report about a
  person. The member API already refused a banned person every call;
  the desk's API now refuses their writes too (`_refuse_banned`, asked
  only of users, only on writes). The events Lambda (`follow_ban`)
  hides their visible posts with the reason `banned` and, when the ban
  is lifted, puts back those and only those; a post still being checked
  when its author is banned is never published. `GET /api/people` lists
  everyone who has opened the app; the desk's role reads `ENTITY#USER`
  for it. In the desk: "People in the app" on the People screen, with
  **Ban** and **Unban**, and **Ban** on a reported person's card.
  **Not built:** telling a banned person why, beyond "this account is
  blocked"; an appeal.

### B9. Push

- **Needs:** D18, A5. B3, B5. O7 before it can be tried on a phone.
- **Builds:** the sender in the events Lambda (token-signed requests to
  Apple, the right environment, dead tokens removed on Apple's answer),
  the triggers, the per-person daily cap, the `push` flag.
- **Done when:** in tests, the collected pushes for a seeded day are
  exactly the expected ones and carry no user-written text.
- **Built 2026-11-14** (`04-api.md`, "Push"; `tests/app/test_push.py`,
  `tests/events/test_push.py`). `PUT` and `DELETE /me/devices/{id}`; the
  four notifications of D18 that have something to happen yet (a friend's
  post, an accepted invite, a name taking the lead, a new cat approved);
  five a day per person; each told once however often its change is
  delivered; a device Apple calls gone is forgotten; the `push` flag (on
  in staging, off in production).
  - **The sending** is `src/events/push.py`: HTTP/2 to Apple with a token
    signed by the team's key, which is what Apple takes and Python's own
    library has neither of. So the events Lambda has packages for the
    first time (`src/events/requirements.txt`: httpx with h2, PyJWT with
    cryptography, every one pinned). They are loaded only when something
    is sent: counters and badges cannot be broken by them.
  - **Nothing is sent yet, anywhere.** No phone can register until N2,
    and the key is the owner's step O7. With either missing the Lambda
    does one extra read per change and stops.
  - **For O7's brief** (written with N2, when a phone can show the
    result): the key goes in with `infra/scripts/set-secret.sh
    apns-auth-key <file>`; its Key ID and the Team ID are not secrets and
    go in `infra/main/variables.tf` (`apns`), by pull request.
  - **Mine:** five a day ("a few", D18); a name's suggester is told only
    when it takes the lead from another name with at least two votes (its
    author's own vote makes a first name "lead"; nobody needs telling);
    a rejected new cat is not told (the app says it); the day is UTC's;
    a post is told to at most 200 friends.
  - **Not built:** "someone asked to be your friend" (friend requests are
    not written yet, D4); the profile's switch and asking the phone's
    permission (N2, G15).

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
- **Built (2026-11-12):** `web/social/` gains `store.js` (one store:
  who you are, the theme, the tab, the page stack, the bar's state),
  `theme.js` (the four themes by the prototype's names, kept on the
  phone), `motion.js` (`makeSpring` and the glass press, ported),
  `ui.js` (icons, the toast, `confirm()`, `openMenu()`), `tabbar.js`
  (Cats, Scan a cat, Home; the lens, its drag, the shrink on scroll),
  `stack.js` (pages slide in from the end edge and go back by the back
  button or a swipe from the start edge; a fade with "reduce motion"),
  and the Home tab with the profile page's settings (language, theme)
  and sign-out. Tested: tabs and lens, the page slide and both ways
  back, reduce motion, the theme menu kept across a reload, Escape and
  arrows in a menu, sign-out asked first, the bar shrinking and coming
  back, three widths, right-to-left. **Not built, on purpose:** the
  bottom sheet, until its first user (E3); the top buttons (search, +)
  with the feed (E2); "Scan a cat" says it is coming until E3.

### E2. The feed

- **Needs:** E1, B3 (B4 for vote cards).
- **Builds:** post cards, several photos, like, the photo's menu, cat of
  the day, paging, the top buttons.
- **Built (2026-11-12):** `web/social/data.js` (the data layer: the
  feed's pages, the cats, likes, deleting a post, the regions' names);
  `feed.js` (the prototype's card: avatar, "met *cat*", the photos one at
  a time with their count, the like on glass over the photo, the text,
  the time and, for its author, the area; cat of the day at the top; the
  next page fetched before the end is reached; empty and failed states);
  the photo's menu ("See *cat*", and for its author "Delete post", asked
  first); `cat.js`, a first cat page (photo, name, description, how often
  you met it, more photos), which E4 completes; the top buttons (search,
  +), which say what they will open until E3 and E4. A like changes on
  screen at once and is taken back, with a toast, if it does not go
  through. Photos from the member API keep one address per photo, like
  the desk's (`web/lib/photos.js`). **Not built, on purpose:** vote cards
  (B4), "Show on map" in the photo's menu (E5), reporting (B8).

### E3. The capture flow

- **Needs:** E1, B3, B6. D13 for the location words.
- **Builds:** the camera, the four pages, both entries (scan and "+"),
  every ending in `01-product.md`'s table, on the outbox; the result
  surviving a reload; the three frames per press (D12: on) behind the
  `capture_burst` flag; the waiting state of a post for a new cat (D7).
- **Done when:** the six endings each write exactly what the table says
  (a test per ending against the local app); with the network off, an
  encounter is posted and everything arrives when it returns; the pick's
  record is what today's Capture writes.
- **Built (2026-11-12):** `web/social/scan.js`. "Scan a cat" opens the
  camera (the in-page viewfinder where the browser gives one, the phone's
  own camera through a file input everywhere); one press, one photo, then
  "Which cat?" (the model's three when it has ranked, then every cat;
  without a model, every cat), "You met X" with "Encounter #N", the
  new-cat form (name idea, coat, place, traits) and the post (the photos,
  up to four, a description, the area switch with D13's words). "+" opens
  the post page with "Take a photo" and "Tag a cat". The endings go
  through today's outbox in one write each (`finishEncounter`): the
  encounter and its photos as Capture sends them, the pick (`new` for a
  new cat), and, once every photo is confirmed, the proposal and the post
  (`after`, sent in order; 425 waits). A post shows in its author's feed
  at once as "Sending" or "Waiting for an admin to confirm the new cat".
  The flow survives a reload. New terms are accepted before anything is
  shared. Tested: every ending, "+" with no cat, a reload, a dead signal,
  new terms. **Not built:** the camera opening as a circle from the tab,
  the flash (no torch in an iPhone's web view), three frames per press
  (D12, the `capture_burst` flag), the service worker sending posts with
  the app closed (Chrome on Android only; the open app sends them).
- **Pages 1, 2a and 2b drawn as the prototype draws them (2026-11-13):**
  "Which cat?" has the photo just taken at the top between Close and
  Retake, the model's three as large photos (two and one), and every
  other cat four to a row after a dashed "New cat" tile; tiles are
  photos only, and a cat with no photo yet shows its name. "You met X"
  has the cat's photo with yours over its corner, "Usually near …" and
  the cat's name poll (the one on its page, `NamePoll` in `poll.js`;
  a vote from here is an ordinary vote). The new-cat form has the tall
  photo strip with "Add photo · 1 of 4", the coats with their colours
  (tokens.css), and the prototype's chips. Both pages end in two buttons
  that stay at the foot of the screen: "Just save" / "Create a post",
  "Just add" / "Add & post". The top button is Close on the flow's first
  page and Back after it (`pageBefore` in `scan.js`): back from "You
  met" is "not this cat". Choosing a cat for a post ("Tag a cat" from
  "+", or "Change") comes straight back to the post. The model is not
  served in the tests, so the test of the three candidates stands in for
  `recognition.js` at its one meeting point with `scan.js`.
- **Pages 3 and 4 the same way (2026-11-13):** the post page has its
  title and "Post" in the bar at the top; "You met **X**" with the cat's
  face and "Change" (from "+": "Tag a cat · Optional", and a tag can be
  removed); the photos large and numbered "1/2", with "Add photo · 1 of
  4", or one large "Take a photo" when there is none; the description
  in a card with its count; "Add location" with the small map and "Near
  Aranne Library" when the phone is inside a place the campus names
  (`placeAt` in `scan.js`, the server's `region_at` on the same rounded
  point; a test holds the two together); "Save without posting" as a
  quiet line after a scan. "Tag a cat" from "+" is the prototype's page
  4: every cat by name, three to a row, the chosen one ringed, no "New
  cat". **The flow no longer freezes as it opens** (2026-11-14): it
  started the recognition model inside the tap, on the page's thread,
  which stopped every touch for seconds on the owner's iPhone, from "+"
  and from "Scan a cat" alike. The model now runs in the runtime's
  worker and starts after the screen is drawn (`docs/notes.md`, "The
  iPhone app"). **A place the phone learns late still reaches the post:** GPS
  takes seconds and the first photo does not wait for it, so the
  encounter often went to the server with no place while the page showed
  one. The outbox now sends the place as a step of its own, before the
  answer and the post, and `POST /api/encounters` takes a place for an
  encounter that has none (and never replaces one). **Not yet:** the
  sideways swipe back, and removing a photo from
  the strip: a photo taken is already part of the encounter in the
  dataset, and whether "remove" should also delete it there is the
  owner's to decide.

### E4. The gallery, a cat's page, the poll

- **Needs:** E1, B2, B4.
- **E4a, built 2026-11-13:** the gallery and the cat's page, from what
  the API already answers (`GET /cats`, `GET /cats/{id}` and its posts).
  The gallery (`web/social/gallery.js`) opens from the feed's top-left
  button and from its search bar, which hands over to a real search
  field; two columns of photos cut to the prototype's heights; sorted on
  the phone by recently seen, most posts, newest and name. The cat's
  page: its photos edge to edge, one at a time; the card with the name
  and where it came from, the usual place, the description, posts, likes
  and last seen, and how often the caller met it; who posted it lately.
  Left out until their backends exist: the grade and "Highest GPA"
  (B7b), the map button (E5; both built since). The name poll joined the page with B4a:
  each option a bar of its share, the leader marked, the choice ringed;
  a tap votes, a tap on your choice takes it back, and a name typed
  below joins the poll, marked while it is being checked. The gallery slides in
  as a page from the end edge; the prototype brings it from the start.

### E5. The map

- **Needs:** E4. O12 for it to be right.
- **Builds:** the drawn campus from the regions file and the prototype's
  shapes, dragging, the habitat sheet. The feeding spots (D10) are drawn
  once the designer has drawn one (G6); until then the file carries them
  and the map does not show them.
- **E5a, built 2026-11-13** (`web/social/map.js`), from the prototype:
  the campus as one drawing in the theme's colours, dragged with a
  finger (it follows a third as far past an edge, glides on a little,
  and stops inside its edges); the five habitats, each an area and a
  name to tap, with up to three of its cats as round photos; the sheet
  with the habitat's name, how many cats live there, and each cat with
  its grade. "Show on map" on a cat's page and in a photo's menu opens
  it on the cat's usual place (`regionId`, set in the desk's "Public
  info"); a cat with none opens the whole campus. The map takes the
  whole screen: the tab bar and the page's back button step aside, and
  the way back is in the sheet. No route of its own: `GET /cats` and
  the regions file.
  - The areas are the prototype's, keyed by region id in the module. A
    test holds them to `web/regions.json`: when the owner's real places
    arrive (O12) the drawing is made again.
  - **Mine:** "Scan a cat" in the sheet of a habitat with no cats, where
    the prototype has the sentence alone.
  - **Not built:** feeding spots (G6); the map's opening animation.

### E6. Home, profile, settings

- **Needs:** E1, B1 (B7 for the cards' numbers, B10 for delete).
- **E6a, built 2026-11-13 (the owner's order: Home and profile first):**
  the two screens as the prototype draws them, from what the API already
  answers (`GET /me` with its counters, `GET /me/posts`). Home: the glass
  pill (name, cats met, since), which folds to the photo while scrolling;
  the Friends card with the sitting cat (`web/social/mascot.js`) and the
  caller's own row; "My posts". The profile: the default cat-face photo,
  name, username, "My posts" four to a row, the settings and account rows
  E1 had. Left out until their backends exist, not drawn with made-up
  numbers: friends (E7), achievements (E8), changing the name and photo
  (B1), the notifications switch (N2), the phone number (D5), privacy
  policy (A6), delete (B10). The profile still slides in as a page; the
  prototype grows it out of the pill.
- **Also in E6a:** the glass bar over a tab (the feed's buttons, Home's
  pill) stays at the top. It had scrolled away with the first card since
  E2, which no test looked at; one does now.
- **From now on** a screen's pull request carries the prototype rendered
  beside the built screen (the owner's ask, 2026-11-13): the prototype's
  `.dc.html` files open in the test browser with its runtime as
  `support.js`.

### E7. Friends

- **Needs:** E6, B5 (B8 for block and report).
- **E7a, built 2026-11-13** (`web/social/friends.js`), from the
  prototype's friends page in `Feed.dc.html`:
  - Home's Friends card is the first three of you and your friends by
    cats found in all, each with the cats they met last; the card and
    the button beside the profile pill open the friends page.
  - The page: "This month" / "All time", the podium, a search over the
    list the phone already holds, every friend with "Remove from
    friends" in its menu.
  - "Add friend" is the invite alone (D5: no contacts yet): the link,
    **Copy link**, **Share…**.
  - A person's page: the name, "N cats found", "Friends since", their
    latest posts. A post's author in the feed opens it.
  - **Not in the prototype, mine:** under the link, "Got a link from a
    friend?" with a field to paste it into. A link tapped in a chat
    opens the browser, not an app added to the home screen, and on an
    iPhone the two share nothing; without the field a friend's link
    could not be used from the installed app until links open the app
    (N4). A link opened where the app does run (`app.html?invite=…`) is
    kept across the sign-in and makes the friendship once the app is up.
  - The feed's name-vote card: "Maya voted to call Simba “Mango”", the
    poll's first three names with percentages and the friends who chose
    each, "128 votes · You and 2 friends voted", **All names**.
  - **Not built:** Block and Report (B8), contacts (D5), the page's
    opening animation from the card, the folded tab bar.

### E8. Achievements

- **Needs:** E6, B7.
- **E8a, built 2026-11-13** (`web/social/achievements.js`), from the
  prototype: Home's card ("5 points · 2 badges", the newest three
  badges), and the sheet over the app: the points, the level with its
  bar, three tiles, every badge earned or locked, how points are earned.
  The `achievements` flag is on in both accounts' settings. **Mine:** a
  tap on a badge says how it is earned; drawings and colours for Dean's
  List and Cat Whisperer, which the prototype shows locked only. **Not
  built:** the sheet's opening animation from the card.

### E9. The states nobody drew, offline, accessibility

- **Needs:** the screens above.
- **Builds:** every row of "States the design does not draw"
  (`05-client.md`), with a screenshot of each for the owner; the contrast
  test; touch-target sizes.
- **The start itself, 2026-11-14:** a launch that stalls was a black
  screen with nothing to press. The page now says it is loading before
  any of the app has arrived, names the step when it is slow, bounds
  every step, and offers "Try again" and "Reset the app on this phone"
  (`web/app.html`, `boot` in `main.js`).
- **What the phone can say, 2026-11-14 (mine: no design):** the page
  keeps the last eighty things the app did, with a line for every time
  the screen stopped answering, and Profile has "App info" to read and
  copy it (`web/social/appinfo.js`, `trail.js`); the slow start and the
  failed start offer "Copy app info" too. The service worker keeps each
  page under its own name and opens the kept copy when the network has
  not answered in four seconds; the member app registers it itself.
- **A start with no signal, 2026-11-14:** the app could be opened from
  the kept page and then said "could not start", because the first thing
  it does is read the account. It now opens with the account as this
  phone last read it (the same sign-in only), so a cat can be
  photographed where there is no signal and the photos go later; the
  account is read again when the phone is back. A sign-in the API no
  longer takes goes to the sign-in screen, where it used to say "could
  not start".
- **Built 2026-11-13.** The rows of that table that were missing:
  - *Nothing here yet:* the mascot, one line and the next thing to do
    (`Empty` in `mascot.js`) in the feed ("Scan a cat"), the gallery, a
    search with no match and the blocked list; a feed or gallery that
    could not be loaded says so the same way, the feed with "Try again".
  - *No signal:* the feed keeps its first page on the phone, per person,
    and shows it with one quiet line when the server cannot be reached;
    it asks again by itself when the signal returns. A like or a vote
    already said it did not go through.
  - *A post being sent:* a ring over its photo that fills as the photos
    arrive, and under it the outbox's own reason for waiting ("No
    signal…", or "Trying again. Last try: …").
  - *Not published:* a post of the caller's that others cannot see
    reads "Not published" in My posts; a tap says "This wasn't
    published", with no reason, and removes it in one more.
  - Already there: no model, "Being checked", a new cat's post waiting,
    "—" for no grade, "No feeding logged yet", posting while photos
    upload, the refusal at sign-in, the terms before the first post, and
    deleting one's own post from the photo's menu (G11).
  - **Contrast** (`tests/web/test_contrast.py`, no browser): thirteen
    pairs of words and ground in each of the four themes, by WCAG's
    formula on `tokens.css`. All pass 4.5 to 1 but one: white on the
    prototype's red, the words of a "Delete post" button, is 3.7 to 1 in
    every theme. Listed in the test as known, for the designer; it may
    not get worse.
  - **Touch targets** (`tests/web/test_touch_targets.py`): every control
    on every screen is pressed 21 px off its centre, each way. Those the
    design draws smaller than 44 px (chips, a sheet's close, the map's
    place names, the friends' period switch, "Change") keep their look
    and have room around them that takes the touch (`app.css`, "room for
    a finger"). Not held to it: the two names inside a post's heading,
    which are text in a sentence; the photo beside them and the photo's
    menu lead to the same places.
  - Pictures: `member-feed-empty`, `member-feed-no-signal`,
    `member-feed-failed`, `member-gallery-no-match`,
    `member-post-sending`, `member-post-not-published`.

### E10. Languages and right-to-left

- **Needs:** D17. E9. O14 before a language is offered.
- **Builds:** `he.json`, `ru.json`, `ar.json` as drafts; the language
  menu; a Hebrew and an Arabic screenshot of every screen.
- **Built 2026-11-13, as drafts.** `web/i18n/he.json`, `ru.json` and
  `ar.json` say everything English says (`tests/web/test_languages.py`:
  the same keys in the same order, the same placeholders, and exactly
  the plural forms each language's rules can ask for: three in Hebrew,
  four in Russian, six in Arabic). Written by the model, not by a
  speaker: **nobody has read them** (O14). They avoid addressing the
  reader by gender where the language allows.
  - **Which languages the profile offers is the account's setting**
    (`languages` in `infra/main/variables.tf`, sent as
    `flags.languages`): English alone in production, all four in
    staging, so a draft can be read on a phone before it is offered.
    The menu names each language in its own words. Choosing one saves
    it with the account and on the phone and starts the app again in
    it; a new phone opens in the account's language; one no longer
    offered falls back to English.
  - **Right to left** was built in from the first line of CSS, so
    Hebrew and Arabic needed no layout change. What a person wrote (a
    post's text, a name being typed) keeps its own direction
    (`dir="auto"`).
  - `tests/web/test_member_languages.py` walks fourteen screens in
    Hebrew, Arabic and Russian and holds each to: no page scrolls
    sideways and nothing visible hangs past an edge. Pictures:
    `member-*-he`, `member-*-ar`, `member-*-ru`. Russian's longer words
    were shortened where they did not fit a button.
  - Found on the way: `tRich` put the number after any plural form that
    said it in words ("one cat found" in Hebrew); such a form now has
    nothing in bold.
  - **Not translated:** the names of the campus places
    (`web/regions.json` has English only, and they are placeholders
    until O12), the desk, and the server's own error sentences.

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
- **Built (2026-11-12):** `scripts/native_bundle.py` packs
  `"frontDoor": "app"`; `infra/main/web.tf` serves `/model/*` with the
  managed response headers policy Managed-SimpleCORS (by its ID, so no
  data source and no new permission to read it); `web/recognition.js`
  takes a `base` origin and, with no service worker, keeps the model's
  bytes in its IndexedDB `files` store. The desk and the scan flow pass
  `config.apiBase` as the base in the app. Not yet run by a person: the
  phone checklist after the next build.

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

- **O3, the first production promote,** which the owner postponed on
  2026-11-12 to here. It will be the first ever and the largest: read
  its plan line by line.
- The plan for production shows what staging has run.
- O4, O5, O7 done for production, O4 before the promote; O6.
- `social` on, `frontDoor = app`, by pull requests, promoted by tag.
- Today's collaborators, now users, can still do everything they did.
- Rollback is the flag, then `git revert`.

## After this plan

Android; the feeding screens once designed (G6); live update of `web/` in the
iPhone app; CloudFront for photos if the bill asks; thresholds for the
recognition model when the live record earns them.
