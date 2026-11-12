# The data model

Two tables. `bgucats-data` is the dataset and stays as spec §6.3 and
`infra/main/dynamodb.tf` describe it; this plan adds two fields and one
item to it, all written by the existing API. `bgucats-social` is new and
holds everything people do in the app.

When F2 lands, this file's catalogue moves to `docs/data-model.md` and
covers both tables, so there is one place that lists every key. Until
then the keys of the existing table are in the spec and in the comment
at the top of `dynamodb.tf`.

## The rule that shapes everything

**A person's cat tag is a claim. A label is an admin's.**

| | Written by | Lives in | Means |
|---|---|---|---|
| `SESSION.catId` | an admin, in the desk | `bgucats-data` | this encounter is this cat: the dataset's truth |
| the pick | the person, in the capture flow | `bgucats-data` (`SESSION#{id}` / `PICK`), as today | what they answered to "which cat?", scored against the label |
| `ENC.claimedCatId`, `POST.catId` | derived from the pick, corrected by the label | `bgucats-social` | what the app shows and counts |

The app shows the claim at once and follows the label when one exists.
Recognition templates, exports and the model's score never read a claim.
The open-set rule holds: a wrong "new cat" from a person costs an admin
one merge, and a wrong "it's Simba" from a person never enters the
dataset.

## `bgucats-social`

Same shape as the first table: `PK`, `SK`, three indexes (`GSI1`,
`GSI2`, `GSI3`, each `…PK` / `…SK`), `expiresAt` as the TTL attribute,
on-demand billing, point-in-time recovery, deletion protection,
`prevent_destroy`. A stream with new and old images.

Ids: a user id is a ULID made by the server at first sign-in. Post,
proposal and report ids are ULIDs made on the phone, so the outbox can
retry and land on the same record. Cat, session and photo ids are the
dataset's.

### People

| Item | PK | SK | Holds |
|---|---|---|---|
| User | `USER#{userId}` | `PROFILE` | `email` (never sent to others), `username`, `displayName`, `avatarKey`, `phone` (D5; never sent to others), `language`, `theme`, `notifications`, `inviteCode`, `status` (`active` / `banned` / `deleting`), `termsAcceptedAt`, `createdAt`. On `GSI2` as `ENTITY#USER` / `createdAt` |
| Sign-in lookup | `IDENTITY#{email}` | `META` | `userId` |
| Username lookup | `USERNAME#{username}` | `META` | `userId` |
| Phone lookup (D5) | `PHONE#{hmac}` | `META` | `userId`. The key is an HMAC of the number in international form, keyed with a secret from SSM, so the table holds no list of numbers that can be reversed by trying them all |
| Invite code | `INVITE#{code}` | `META` | `userId`. The code is random, not derived from the username |
| Friend | `USER#{a}` | `FRIEND#{b}` | `since`, `via` (`invite` / `request` / `contacts`). Always written with its mirror (`USER#{b}` / `FRIEND#{a}`) |
| Friend request (D4) | `USER#{to}` | `FREQ#IN#{from}` | `at`. Mirror: `USER#{from}` / `FREQ#OUT#{to}` |
| Block | `USER#{a}` | `BLOCK#{b}` | `at`. Mirror: `USER#{b}` / `BLOCKEDBY#{a}`, so "who must not see me" is one query |
| Device | `USER#{id}` | `DEVICE#{deviceId}` | `apnsToken`, `environment`, `updatedAt` |
| Counters | `USER#{id}` | `STATS#ALL`, `STATS#{yyyy-mm}` | `catsMet`, `encounters`, `posts`, `graded`, `fed`, `namesLed`; `points` on `ALL` only |
| A cat met | `USER#{id}` | `MET#{catId}` | `firstAt`, `lastAt`, `days` (different days), `lastDay`. And `METM#{yyyy-mm}#{catId}` for the month's count |
| Badge | `USER#{id}` | `BADGE#{badgeId}` | `at` |
| An encounter, as the app counts it | `USER#{id}` | `ENC#{sessionId}` | `claimedCatId`, `labelCatId`, `rejected`, `day`, `regionId`, `postId`, `counted` (what the counters were last given for it) |

`ENC` is the bridge between the tables. The capture route that records a
pick writes it; the desk routes that assign, unassign, merge or reject an
app encounter update `labelCatId` or `rejected` on it. The events Lambda
sees the change and corrects `MET`, `STATS`, points and the post's cat.
That is how D8's "taken back if the label disagrees" happens without a
stream on the dataset table.

### Posts

| Item | PK | SK | Holds |
|---|---|---|---|
| Post | `POST#{postId}` | `META` | `authorId`, `sessionId`, `photoIds` (1–4, in order), `claimedCatId`, `proposalId`, `catId` (what is shown: the label, else the claim, else none), `text` (0–280), `regionId` (the area, only if the author shared it), `status`, `hiddenReason`, `likeCount`, `createdAt`, `visibleAt` |
| Like | `POST#{postId}` | `LIKE#{userId}` | `at` |

A post's `status`: `pending` (written, not yet checked) → `visible` |
`hidden` (waiting for an admin, or reported past the threshold) |
`removed` (by its author or an admin).

Its index keys:

- `GSI1`: `AUTHOR#{authorId}` / `createdAt`. Always, so the author sees
  their own pending post.
- `GSI2`: `FEED#{yyyy-mm}` / `{createdAt}#P#{postId}`. **Only while
  visible.** Hiding a post removes these two attributes and it leaves
  every feed.
- `GSI3`: `CATPOST#{catId}` / `createdAt`. Only while visible and a cat
  is shown. The prefix is not `CAT#`, which is the dataset's
  photos-of-a-cat index on the other table and must never be confused
  with it.

### Cats, as the app sees them

| Item | PK | SK | Holds |
|---|---|---|---|
| Public counters | `CAT#{catId}` | `PUBLIC` | `posts`, `likes`, `lastSeenAt`, `gradeSum`, `gradeCount`, `voteTotal`, `leaderKey`, `leaderName`, `nameLocked` |
| Name option | `CAT#{catId}` | `NAME#{nameKey}` | `name` (as typed), `votes`, `suggestedBy`, `status` (`pending` / `live` / `rejected` / `removed`), `createdAt` |
| Vote | `CAT#{catId}` | `VOTE#{userId}` | `nameKey`, `at`. On `GSI2` as `FEED#{yyyy-mm}` / `{at}#V#{catId}#{userId}`, which is how a vote becomes a card in friends' feeds |
| Grade (D9) | `CAT#{catId}` | `GRADE#{userId}` | `value`, `at` |
| Feeding (D10) | `CAT#{catId}` | `FED#{at}#{userId}` | `regionId` |

`nameKey` is the name normalised (NFKC, case-folded, spaces collapsed),
so "mango" and "Mango " are one option.

A cat's description, usual region, coat and status are the admin's and
live on the cat's item in `bgucats-data` (below). The member API reads
them there and adds the counters from here.

**The cat's shown name:** the admin's locked name if `nameLocked`; else
the leading live option; else the admin's `displayName`; else nothing
(D6).

### Proposals, reports, moderation

| Item | PK | SK | Holds |
|---|---|---|---|
| New-cat proposal | `PROPOSAL#{proposalId}` | `META` | `proposerId`, `sessionId`, `nameIdea`, `coat`, `regionId`, `traits`, `status` (`open` / `approved` / `merged` / `rejected`), `catId` (the result), `decidedBy`, `decidedAt`. On `GSI2` as `PROPOSALS#{status}` / `createdAt` |
| Report | `REPORT#{reportId}` | `META` | `reporterId`, `targetType` (`post` / `user` / `name` / `avatar`), `targetId`, `reason`, `note`, `status` (`open` / `actioned` / `dismissed`), `decidedBy`. On `GSI2` as `REPORTS#{status}` / `createdAt` |
| One report per person per target | `REPORTED#{targetType}#{targetId}` | `BY#{reporterId}` | `at`. Counting the partition gives "different people who reported this" |
| Moderation run | `MOD#{kind}#{subjectId}` | `RUN#{at}` | `policy`, `model`, `mode`, `answers` (each question's probability), `outcome` (`pass` / `flag` / `block` / `error`), `acted`, `human`, `humanBy`, `humanAt`, `tokens`, `ms`. On `GSI2` as `MODQ#open` / `at` while it waits for an admin, then `MODRUN#{yyyy-mm}` / `at` |

`kind` is one of `POSTTEXT`, `NAME`, `PROPNAME`, `DISPLAYNAME`,
`USERNAME`, `AVATAR`, `PHOTO`.

### Limits

| Item | PK | SK | Holds |
|---|---|---|---|
| A person's counter for an action | `RATE#{userId}#{action}#{bucket}` | `META` | `count`, `expiresAt` |
| Decision 1 use today (K3) | `SPEND#{yyyy-mm-dd}` | `DECISIONS` | `calls`, `tokens`, `expiresAt` |
| Pushes sent to a person today | `USER#{id}` | `PUSHED#{yyyy-mm-dd}` | `count`, `expiresAt` |

## Added to `bgucats-data`

Written only by the existing API (`src/admin/`), never by the member API.

- **On a cat's item:** `bio` (public, at most 280 characters, the
  admin's) and `usualRegionId`. `adminNotes` and anything else not listed
  as public in `04-api.md` is never sent to a member.
- **`SESSION#{sessionId}` / `RERANK#{version}`:** the re-rank's result
  for an encounter, beside `PREDICTION#{version}` and `PICK`
  (`07-rerank.md`).
- A pick's `choice` may be `new`, for a proposal.

Nothing about a photo, a session or a label changes shape.

## Writes that must be all-or-nothing

Each is one `TransactWriteItems`. A transaction is authorised by the
ordinary item actions, which the roles already have.

| Action | Items, and the condition that makes a retry harmless |
|---|---|
| First sign-in | put `IDENTITY` (must not exist) + put `USER` + put `USERNAME` (must not exist) + put `INVITE`. If `IDENTITY` exists, read it and return that user |
| Choosing a username | put the new `USERNAME` (must not exist) + delete the old + update `USER` |
| Like | put `LIKE` (must not exist) + add 1 to `POST.likeCount` (post must be visible) + add 1 to the cat's `PUBLIC.likes`. Already liked → success, no change |
| Unlike | delete `LIKE` (must exist) + subtract 1 from both |
| Vote | put `VOTE` (its `nameKey` must still be what was read) + subtract 1 from the old option + add 1 to the new (must be `live`, or `pending` and the voter's own) + adjust `voteTotal` |
| Take a vote back | delete `VOTE` (same condition) + subtract 1 |
| Suggest a name | put `NAME` as `pending` (must not exist) + the suggester's vote for it, as above. If it exists: just the vote |
| Accept a friend | put both `FRIEND` items + delete both `FREQ` items |
| Invite link | put both `FRIEND` items (must not exist; neither may have blocked the other) |
| Block | put `BLOCK` + `BLOCKEDBY` + delete both `FRIEND` items and any `FREQ` between them |

**Kept by the events Lambda, not by the request:** a cat's `posts` and
`lastSeenAt`, the poll's `leaderKey` and `leaderName`, everything under
`STATS`, `MET`, `BADGE`. They can be a second or two behind and can be
recomputed from the items they summarise. The plan includes a recount
script per counter (B7), because `docs/notes.md` already records what a
stored count that was wrong once does.

## Reading: what the indexes are for

| Index | Partitions | Serves |
|---|---|---|
| `GSI1` | `AUTHOR#{userId}` | my posts, a friend's posts |
| `GSI2` | `FEED#{yyyy-mm}` | the feed: posts and votes, newest first, month by month |
| | `ENTITY#USER` | the desk's list of people |
| | `PROPOSALS#{status}`, `REPORTS#{status}`, `MODQ#open` | the desk's queues |
| | `MODRUN#{yyyy-mm}` | moderation, measured |
| `GSI3` | `CATPOST#{catId}` | a cat's recent posts |

**Building a page of the feed** (`GET /feed`):

1. Read the caller's friend ids, block ids and blocked-by ids (three
   queries on `USER#me`; cached for the life of the request).
2. Query `FEED#{month}` backwards, 50 items at a time, into older months
   when one runs out. Stop at 20 cards or after 6 queries.
3. Drop anything from a person in either block list. If `feed_scope` is
   `friends`, drop posts from anyone who is not a friend or the caller.
4. Votes: keep only friends' votes; fold them into one card per cat
   ("Daniel and Noa voted…"). A cat with no friend's vote in the page
   gets no card.
5. One batch read for "did I like these", one for the authors' names and
   avatars. Cats come from the cat list the Lambda already holds.
6. Photo addresses are built from the photo ids
   (`derived/{photoId}/medium-1024.webp`, spec §6.1: any location from an
   id without a lookup) and signed.
7. `regionId` is sent only to the author and the author's friends.
8. The cursor is the last key read, opaque to the client.

The feed is read from an index, and an index can lag
(`docs/notes.md`, "DynamoDB"). So a person's own new post is shown from
the phone's memory at once and is not expected in the next feed read;
nothing is decided on an item's absence from a list.

## Invariants

Each of these gets a test.

1. The member API's role cannot write `bgucats-data`. (An IAM test in
   `tests/checkplan`, on the planned policy.)
2. No response to a member contains another person's `email` or `phone`,
   or a cat's `adminNotes`.
3. A post that is not `visible` has no `FEED#` and no `CATPOST#` keys.
4. A post's photos belong to the post's session, and the session belongs
   to the author. Checked against `bgucats-data` when the post is made.
5. A `FRIEND`, `BLOCK` or `FREQ` item never exists without its mirror.
6. One `VOTE` per person per cat; the options' `votes` sum to
   `voteTotal`.
7. A name is `live` only after a moderation run passed it or an admin
   approved it.
8. `ENC.counted` always equals what `STATS` and `MET` were given for that
   encounter, so correcting it is a subtraction and an addition, not a
   recount.
9. A person in `deleting` or `banned` writes nothing.

## Deleting an account

`DELETE /me` sets `status = deleting` and answers. The events Lambda does
the rest, in an order that can be interrupted and resumed, because each
step is safe to repeat:

1. Sign the person out everywhere and delete the Cognito user.
2. Posts: set `removed`, which drops them from every index.
3. Likes and votes: delete, with the same counter transactions as an
   unlike and a vote taken back. Names they suggested stay as options
   with no suggester.
4. Friends, requests and blocks: delete with their mirrors.
5. Devices, badges, counters, `MET`, `ENC`: delete.
6. The avatar object.
7. `USERNAME`, `PHONE`, `INVITE`, `IDENTITY`, and last the `USER` item.

What stays, per D14's recommendation: the sessions and photos in
`bgucats-data`. Their `submitterHash` is a salted hash, and with the
`IDENTITY` and `ENC` items gone nothing links them to a person. If D14 is
answered otherwise, step 2 also rejects the person's unlabeled sessions
through the desk's existing reject, which deletes the objects and their
versions.

Reports the person made stay, with the reporter id cleared.

## Seeding

`scripts/seed_campus.py` makes the made-up campus for staging, the local
app and the tests. F3 extends it with a dozen people, friendships, posts
with descriptions, votes, a proposal, a flagged item and a report, all
through the real routes, the way it seeds cats today
(`docs/notes.md`, "A seed that goes through the front door is the best
first test").
