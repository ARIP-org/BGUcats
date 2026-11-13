# The API

Three groups of routes: the new member API (`/api/v1/…`, the
`bgucats-app` Lambda), the capture routes that exist and change a little,
and new desk routes for admins (both in the existing `bgucats-admin`
Lambda). Shapes are sketches; the session that builds a route settles its
fields and records them here.

## Conventions

- **Who:** every route needs the Cognito token, as today. "Member" below
  means an active user: not banned, not being deleted, terms accepted.
  With the `social` flag off, every `/api/v1/` route answers 404.
- **Ids from the phone.** Posts, proposals and reports carry a ULID the
  phone made. Sending the same one twice is the same request, answered
  the same way. Likes, votes, blocks and devices are `PUT` and `DELETE`
  on a key, so they repeat safely by construction.
- **A status code is a contract with the outbox**
  (`docs/notes.md`). `web/outbox.js` drops a request on a permanent
  error. So: 400 and 403 mean "never"; 404 means "never" and is used
  only when retrying cannot help; **425 Too Early** means "not yet" (since
  B3a: a post whose photos are still uploading, code `not_ready`); 429
  means "later" and carries `retryAfter` in seconds. The outbox already
  retries both: `isPermanent` in `web/outbox.js` lists 400, 403, 404 and
  409 only. (The plan first said "409 with retry"; 409 is in that list, so
  it would have been dropped.)
- **Errors:** `{"error": "words for a person", "code": "machine_word"}`.
  Codes used below: `not_admitted`, `terms_required`, `banned`,
  `rate_limited`, `not_ready`, `not_yours`, `gone`, `name_taken`,
  `not_accepted`, `already_posted` (409, since B3b), and `try_again`
  (503: a race that a retry resolves; the outbox retries a 5xx).
- **Lists:** `?cursor=` in, `"cursor"` out, absent on the last page.
  Opaque.
- **Photos:** every photo in a response is
  `{"thumb": url, "medium": url}`, signed, with the long cache header the
  app already relies on (`stablePhotoUrl` in `web/app.js`).
- **Never sent to a member:** anyone else's email or phone; a cat's
  `adminNotes`; another person's pending items; moderation scores.
- **Reads that decide "exists or not" are strongly consistent,** as
  `_item` in the existing handler is.

A person, as others see them:
`{userId, username, displayName, avatar, found, since}`, plus
`friend` (`yes` / `requested` / `incoming` / `no`) relative to the caller,
`friendSince` and `me` (since B5a; only `yes` and `no` until there are
requests). Only what is published: a name or photo still being checked is
its owner's alone.

## The member API: `/api/v1`

### Me

| Route | Does |
|---|---|
| `GET /me` | The caller's profile, role, counters, and the **flags**. Creates the user on the first call (D1's rule applies: `not_admitted` if the address is not let in). The client calls this first, always. Since B3b `counters` is `{all, month}`, each `{catsMet, encounters}`, a second or two behind a pick or a label |
| `POST /me/terms` | Records acceptance of the terms' current version. Until then every write answers `terms_required` |
| `PATCH /me` | `displayName`, `language`, `theme`, `notifications`: only the fields sent change, and the answer is `GET /me`'s. A new display name is shown to its owner at once (`namePending: true`) and to others after moderation. The name needs the terms and counts against 10 changes a day; the settings need neither. Since B1a |
| `PUT /me/username` | Chooses the username: 3–20 of `a-z 0-9 . _`, a letter or digit at each end, no two separators in a row, stored in lower case; `bad_username` otherwise. `name_taken` if in use or on the reserved list. One transaction, so the old name is free as the new one is held. Needs the terms; 10 tries a day, a refused one included. Published at once until C1 checks it. Since B1c |
| `POST /me/avatar` | Returns an avatar id and a presigned upload that pins key, type and size (JPEG, 200 KB). Needs the terms; 5 a day. Since B1b |
| `POST /me/avatar/{avatarId}/complete` | Confirms the object, checks its first bytes, refuses one that is not a JPEG or still carries EXIF, XMP or IPTC (`bad_photo`, and the object is deleted); the avatar goes to moderation, its owner's meanwhile (`avatarPending`). Answers like `GET /me`. Removes the photo it replaces and any upload never confirmed |
| `DELETE /me/avatar` | Removes it, published or waiting: every version of every object under the person's `avatars/` prefix |
| `PUT /me/devices/{deviceId}` | Registers this phone's push token and Apple environment |
| `DELETE /me/devices/{deviceId}` | On sign-out, and when the switch is turned off |
| `GET /me/posts` | The caller's posts, pending and hidden ones included, each with its state |
| `GET /me/invite` | `{code}`. The link is built on the phone, from the address the app was opened at (the custom domain arrives with N4). `GET /me` carries the same code. Since B5a |
| `GET /achievements` | Since B7a. `{points, level: {level, from, next}, counters: {catsMet, encounters, posts}, badges: [{id, earned, at}], rules: [{id, points}]}`. `next` is null at the top level. The badges are every one in `web/achievements.json`, in its order. Names and the rules' text are the app's strings, by id |
| `DELETE /me` | Body `{"confirm": "delete"}`. Starts deletion and signs the caller out (`03-data-model.md`) |
| `PUT /me/phone`, `DELETE /me/phone` | D5 only |

### People

| Route | Does |
|---|---|
| `GET /friends?period=month\|all` | `{period, people, requests}`. `people`: the caller (`me: true`) and their friends, each a person with `found` for the period and `cats`, the ids of the three cats they met last; most found first, so the podium is the first three. `requests` is 0 until there are requests. Default `month`. Since B5a |
| `GET /users/{userId}` | `{person}`, with all-time `found` and `cats`. Their posts are a second call. `gone` for nobody, or an account that is banned or being deleted. Since B5a |
| `GET /users/{userId}/posts` | Their visible posts, newest first, a page of them (D3: the whole campus reads every visible post). Since B5a |
| `DELETE /friends/{userId}` | Removes the friendship, both sides, in one transaction. The same answer if they were not friends. Since B5a |
| `POST /invites/{code}/accept` | Makes the caller and the code's owner friends, in one transaction. `{person}`, the same whether new or already friends; `gone` for an unknown code, an account that is going away, or a block between them; `own_invite` (409) for the caller's own. Needs the terms; 30 a day. Since B5a |
| `POST /friends/requests`, `GET /friends/requests`, `POST /friends/requests/{userId}/accept`, `DELETE /friends/requests/{userId}` | D4, if requests are chosen |
| `PUT /blocks/{userId}`, `DELETE /blocks/{userId}`, `GET /blocks` | Since B8a. Block: the block, its mirror and the end of the friendship, in one transaction; `{userId, blocked}`; twice is once; 50 a day. Unblock: both items; they are not friends again. List: the people the caller blocked, newest first (never who blocked the caller). While a block stands, either way: neither is in the other's feed or a cat's posts, `GET /posts/{id}`, `GET /users/{id}` and its posts answer `gone` exactly as for nobody, and an invite between them does nothing |
| `POST /reports` | Since B8b. `{reportId, targetType, targetId, reason, note?}`. `targetType`: `post`, `user`, `avatar`, `name` (id `{catId}/{nameKey}`). Reasons are a fixed list (`src/common/reports.py`: spam, offensive, harassment, privacy, not_cat, other). Always answers `{reported: true}`, whether it was the first, a repeat, one's own post or nothing at all, so a reporter learns nothing. 20 a day; does not need the terms |
| `POST /contacts/match` | D5 only. Numbers in, the people among them out; nothing stored |

Search over friends is done on the phone, over the list it already has.

### Cats

| Route | Does |
|---|---|
| `GET /cats` | Every public cat: id, shown name and where it came from (poll, admin, none), cover photo, region, coat, GPA (computed, or null for "—"; absent with the `gpa` flag off), posts, likes, last seen, last fed, first seen. Plus today's cat of the day. Sorted and searched on the phone. A cat that is still a proposal is never in it |
| `GET /cats/{catId}` | The same (`gpa` included, since B7b: one decimal, 4.0 for the most popular cat, null for a cat nobody met in three months or with the `gpa` flag off), plus the description, a few more photos, the poll's summary, and the caller's own vote. Since B3b `met`: `{encounters, days, firstDay, lastDay}` for the caller and this cat, or null |
| `GET /cats/{catId}/names` | Live options with votes, most first, the leader marked, whether the name is locked; the caller's choice; the caller's own pending or refused suggestion with its state; and the cat's `name` and `nameSource` as these options make them (the leader is worked out from the options read, so the page that just voted is never a moment behind). The admins' own name is an option from the start, with no votes. Since B4a |
| `POST /cats/{catId}/names` | `{name}`. Cleans it, refuses blocklisted ones (`not_accepted`; the blocklist arrives with C1), merges with an existing option, records it as pending with the caller's vote. Answers like `GET …/names`. Needs the terms; 10 a day, 3 per cat. Since B4a |
| `PUT /cats/{catId}/vote` | `{nameKey}`. Moves the caller's vote: one transaction, conditional on the vote and on both options being as they were read. Answers like `GET …/names`. Needs the terms; 60 an hour. Since B4a |
| `DELETE /cats/{catId}/vote` | Takes it back. Answers like `GET …/names`. Since B4a |
| `GET /cats/{catId}/posts` | Visible posts of this cat |
| `POST /cats/{catId}/feedings` | `{feedingId, spotId?}`. Logs that the caller fed this cat (D10). Limits: six a day; one per cat every four hours. Answers with the cat's new "last fed" |

There is no route to grade a cat: GPA is computed (D9).

The desk gains `POST /api/cats/{catId}/feedings/{feedingId}/remove`
(admins), for a feeding that was reported or wrong.

**Cat of the day:** chosen on the server from the Israel date, so
everyone sees the same cat and nothing is stored: among active cats seen
in the last 30 days, the one at `hash(date) mod count`.

**Regions and feeding spots** are a file shipped with the client and
read by the API (`web/regions.json`, O12): for each region an id, names
per language, a centre and radius; for each feeding spot an id, names, a
place and its region. The map is drawn from it; no route.

### The feed and posts

| Route | Does |
|---|---|
| `GET /feed` | A page of cards, newest first: posts, and friends' name votes folded per cat (`03-data-model.md`, "Building a page of the feed"). A vote card (since B5a): `{type: "vote", cardId, createdAt, cat: {catId, name, cover}, name, voters, friendsVoted, poll}`: what the newest of the friends' votes says and which friends say it, and the poll as `GET /cats/{id}/names` answers it, each option with the `friends` who chose it. Built from the poll as it is, so one card holds every friend's vote; the cursor carries the cats already shown, so a cat has one card however many pages its votes span. Each post: author (with `friend` since B5a), cat (or "new", or none), photos, text, `likes`, `liked`, time, and `region` if the caller may see it: the author and, since B5a, the author's friends |
| `POST /posts` | `{postId, sessionId, photoIds, claim, text?, shareRegion}`. Checks the session is the caller's and every photo is in it and finished uploading (`not_ready` otherwise). Writes the post as pending. `claim` is `{catId}`, `{proposalId}` or null. One post per encounter: another post id for an encounter whose post is not removed is `already_posted` (409). Records the post on the encounter (`ENC.postId`), so the post follows the label |
| `GET /posts/{postId}` | One post. Its author also gets its state, which is how "being checked" is shown and polled |
| `DELETE /posts/{postId}` | The author removes it |
| `PUT /posts/{postId}/like`, `DELETE …/like` | Like, unlike. Answers with the new count |
| `POST /proposals` | `{proposalId, sessionId, nameIdea?, coat?, regionId?, traits?}`. A new-cat proposal for an encounter of the caller's. Coat, region and traits are from fixed lists (`src/common/proposals.py`; region may be `elsewhere`). Nothing about it is public until an admin decides; a post that names it is held until then (D7). One per encounter (`already_proposed`, 409) unless the earlier one was rejected; 10 a day. Since B6 |
| `GET /me/proposals` | The caller's proposals, newest first, with their status and, once decided, the cat. Since B6 |

**The area on a post** is never taken from the phone's word. When
`shareRegion` is true the server takes the session's stored location
(already rounded to about 100 m), finds its region in the regions file,
and stores only the region id on the post. No location on the session →
no area.

## The capture flow, end to end

What the phone sends, in order, for "scan, choose Simba, write two lines,
post". Steps 1–4 exist today and keep their write order.

| # | Request | Lambda | Notes |
|---|---|---|---|
| 1 | `POST /api/encounters` | admin | the encounter, with its first photo, as today |
| 2 | `POST /api/encounters/{id}/media` | admin | the photo's record as `pending`; a presigned upload |
| 3 | upload to S3 | | then the process Lambda, on the S3 event |
| 4 | `POST /api/photos/{id}/complete` | admin | flips to `unlabeled`, conditional on `pending` |
| 5 | `POST /api/encounters/{id}/rerank` | admin | only if `rerank_mode` is not off; the phone never waits on it (`07-rerank.md`) |
| 6 | `POST /api/encounters/{id}/pick` | admin | the answer and the ranking that was shown. `choice` may be `new` (since B6); the route also writes the `ENC` item in the social table (since B3b) |
| 7 | `PUT /api/v1/cats/{catId}/vote` | app | if they voted on the "You met" page |
| 8 | `POST /api/v1/proposals` | app | only for a new cat |
| 9 | `POST /api/v1/posts` | app | only if posting |

All of it rides the outbox. Steps 8 and 9 wait in the queue until every
photo of the encounter has passed step 4, so `not_ready` is rare and
means only "try again shortly".

The embedding, the three candidates and their order are computed on the
phone, as today.

## Existing routes that change

| Route | Change |
|---|---|
| every capture route (`/api/encounters*`, `/api/photos/{id}/complete`, `GET /api/recognition/vectors`) | open to every user, not only to the allowlist. Two access levels, as today: admins, and any user (a collaborator is a user, R1) |
| `POST /api/encounters/{id}/pick` | writes `ENC` (since B3b); accepts `new` (B6) |
| the desk's assign, unassign, merge and reject | for an app encounter, also update `ENC` (`labelCatId`, `rejected`), which is what corrects the person's counters and their post's cat. Since B3b. A merge gives the source the target's cat; labeling a session also updates the encounters merged into it. A rejected encounter's post is removed: its photos are gone |
| `PATCH /api/cats/{id}` | accepts `bio` and `usualRegionId` |
| `GET /api/me` | unchanged for the desk. The member client uses `/api/v1/me` |

The desk's own `GET /api/cats` stays open to every user for now: today's
Capture reads it for "Another cat…". It becomes admins only in the pull
request that moves Capture to `/api/v1/cats` (B2 and E3), not before.

**The desk routes below are the minimum that lets an admin act** on what
users send (R1). They are plain lists with approve and reject in the
desk's current style, until the admin desk is designed.

## New desk routes (admins only)

| Route | Does |
|---|---|
| `GET /api/moderation/queue` | What waits for a person: flagged, errored, or everything while unchecked items are held |
| `POST /api/moderation/{kind}/{id}/resolve` | `{outcome: approve \| reject}`. Applies it, and records whether the admin agreed with the model: the measurement |
| `POST /api/moderation/{kind}/{id}/rerun` | Asks for a fresh run of a stuck item |
| `GET /api/moderation/stats` | Per question: how often the model and the admin agreed at the current thresholds, and what other thresholds would have done |
| `GET /api/reports`, `POST /api/reports/{id}/resolve` | Since B8b. The queue (`?status=`, default `open`): one entry per thing reported, oldest first, with the thing as an admin needs to see it, how many people reported it, and each report's reason, note and reporter's username. Resolve `{action: dismiss \| hide \| remove}` answers every open report about that thing: `dismiss` closes them and puts back a post the reports themselves had hidden; `hide` and `remove` act on a post; `remove` on a name takes it out of its poll. `ban` arrives with B8c |
| `GET /api/proposals`, `POST /api/proposals/{id}/approve`, `…/merge`, `…/reject` | Since B6. `GET ?status=` (default `open`), oldest first, with the session's photos and the proposer's username. Approve `{name?}` (default the name idea) creates the cat with the proposal's id, sets its coat and usual place from the proposal, and labels the session with the queue's assign; merge `{catId}` labels it as that cat; reject closes only the proposal (the session stays in the queue). Labeling updates `ENC` as any label does; the events Lambda then publishes the waiting post under the cat, or hides it on reject. A second, different decision is 409. Shown at the top of the desk's Queue |
| `GET /api/people`, `POST /api/people/{userId}/ban`, `…/unban` | The list of users; a ban refuses every write and hides their posts |
| `POST /api/posts/{postId}/hide`, `…/restore`, `…/remove` | Since B8b. Marks the post (`modAction`); the events Lambda carries it out with the cat's counters. A removed post is not put back |
| `GET /api/cats/{catId}/names` | Since B4b. Every option whatever its status, most votes first, each with its votes, whether it leads and its author's username; the name the app shows now and why (`source`: `locked`, `poll`, `admin`, `none`); the lock and who set it |
| `POST /api/cats/{catId}/names/remove` | Since B4b. `{nameKey}` removes an option; its votes go with it, and the name cannot be suggested for this cat again. The key is in the body, not the path as first planned: a name may hold a slash. Only marks the option; the events Lambda takes the votes away. Removing twice is removing once. Answers like the `GET` |
| `POST /api/cats/{catId}/name-lock` | Since B4b. `{name}` locks the shown name (any name, up to 80 characters); null unlocks. The poll goes on underneath. Answers like the `GET` |
| `POST /api/encounters/{id}/rerank` | Listed above; any member, own encounter |

## Push

Sent by the events Lambda, never by a request. Payloads carry no text a
person wrote: "Maya posted a cat", not the description, so an unchecked
or later-removed text never sits on a lock screen. Tapping one opens the
post or the friends screen by id.
