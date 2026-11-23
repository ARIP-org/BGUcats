# The data model

Two tables. `bgucats-data` is the dataset and stays as spec §6.3 and
`infra/main/dynamodb.tf` describe it; this plan adds two fields and one
item to it, all written by the existing API. `bgucats-social` is new and
holds everything people do in the app.

`docs/data-model.md` lists every key of both tables, the existing one
taken from the code and kept true by `tests/test_data_model_doc.py`, the
social one since F3 created it.

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

Its items and keys are in `docs/data-model.md`, "bgucats-social", since
the table was created (F3). This file keeps what is not a list of keys:
the rules, the transactions, the invariants.

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
8. `STATS` and `MET` are what the person's `ENC` items add up to. The
   events Lambda recounts them from all of a person's encounters on every
   change (a few hundred items at most), rather than adding and
   subtracting, so a change delivered twice, late or out of order still
   leaves the right numbers. (The plan first kept an `ENC.counted` field
   for adjusting; B3b found the recount simpler and safe to repeat.)
9. A person in `deleting` or `banned` writes nothing.
10. A post with an open proposal is never visible, and a proposed cat is
    in no member's cat list until an admin approves it (D7).
11. A cat's `pop` equals what its counted encounters give, so a recount
    reproduces every GPA.

## Deleting an account

**Built in B10a (2026-11-23), except step 1 (B10b).** `DELETE /me` sets
`status = deleting` and answers; it also deletes the profile photo's
objects (step 6), because the events Lambda has no access to the bucket,
and lists every cat's id on the profile (`deletingCats`), because the
events Lambda cannot read the dataset where cats are listed. The events
Lambda does the rest (`delete_account` in `src/events/handler.py`), one
step per change: each step ends by moving `deletionStep` on, and that
change comes back through the stream to start the next. Every step is
safe to repeat, so a step stopped half-way is run again by the mapping's
retry and finds its finished part done
(`tests/app/test_delete_account.py`).

1. Sign the person out everywhere and delete the Cognito user. **Not
   built (B10b):** the events role has no `cognito-idp` permission. Until
   then the same sign-in answers `gone` while the job runs, and once it
   has finished makes a new, empty account.
2. Posts: set `removed` (`hiddenReason = deleted`), which drops them from
   every index, and their cat's counters are taken back; `authorId` and
   `GSI1` go too, so the post no longer names its author. The likes
   others gave them are deleted, each as an unlike. Proposals stay for
   the desk, with `proposerId` and `GSI1` removed.
3. Likes and votes: delete, with the same counter transactions as an
   unlike and a vote taken back. Names they suggested stay as options
   with no suggester. Their feedings are deleted, and each cat's "last
   fed" follows (`count_feeding`). No index lists a person's likes, and
   the Lambda's role has no Scan: every listed person's posts are looked
   at, which is thousands of reads at most on one campus. A post whose
   author was deleted has no likes left (step 2), so none is missed.
4. Friends, requests and blocks: delete with their mirrors.
5. Reports the person made stay, with the reporter id cleared and their
   one-per-person `REPORTED#…/BY#` item deleted; reports about their
   things lose `targetOwnerId`, and one about the person or their photo
   names `deleted`.
6. Devices, badges, counters, `MET`, `METM`, `ENC`, feedings, pushes:
   delete, after taking what they gave each cat's popularity off it.
7. `USERNAME`, `INVITE`, `IDENTITY` (each only while it still names this
   person), the rate counters of the last four days, a last sweep of the
   partition for anything written while the job ran, and last the `USER`
   item. `PHONE` is not written by any route yet (D5): the milestone that
   writes it adds it here.

While an account is `deleting`, or once its profile is gone, the events
Lambda counts, awards and tells it nothing (`_being_deleted`), so a late
change cannot write a piece of it back.

What stays, per D14's answer: the sessions and photos in `bgucats-data`.
Their `submitterHash` is a salted hash, and with the `IDENTITY` and `ENC`
items gone nothing in the app's table links them to a person. **But the
dataset itself still holds the email address** on each photo
(`submittedBy`), on each app encounter (`startedBy`, and in its `GSI2SK`)
and on a contributor's pick (`pickedBy`), and on the allowlist's
`ADMIN#{email}`. Clearing those is a write to `bgucats-data`, which
neither the member API nor the events Lambda may make (invariant 1,
README rule 7): it is the owner's decision how (the desk's API, which may
write the dataset, or a wider events role under `infra/`), and is listed
in `docs/app-backlog.md`. If D14 is answered otherwise, step 2 also
rejects the person's unlabeled sessions through the desk's existing
reject, which deletes the objects and their versions.

## Seeding

`scripts/seed_campus.py` makes the made-up campus for staging, the local
app and the tests. F3 extends it with a dozen people, friendships, posts
with descriptions, votes, a proposal, a flagged item and a report, all
through the real routes, the way it seeds cats today
(`docs/notes.md`, "A seed that goes through the front door is the best
first test").
