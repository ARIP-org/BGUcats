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
8. `ENC.counted` always equals what `STATS` and `MET` were given for that
   encounter, so correcting it is a subtraction and an addition, not a
   recount.
9. A person in `deleting` or `banned` writes nothing.
10. A post with an open proposal is never visible, and a proposed cat is
    in no member's cat list until an admin approves it (D7).
11. A cat's `pop` equals what its counted encounters give, so a recount
    reproduces every GPA.

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
