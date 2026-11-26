# The data model: every key

One place that lists every item the project stores in DynamoDB, with its
key, its index keys, who writes it, and what it is for. Written
2026-11-12 (milestone F2 of `docs/app-plan/`) from the code itself, not
from memory: `tests/test_data_model_doc.py` fails if `src/` writes a key
prefix this file does not name.

The spec's §6.3 is the origin of the first three entities and stays
authoritative for them. The comment at the top of
`infra/main/dynamodb.tf` explains why the extra shapes exist.

**Keep this file true:** a pull request that adds, removes or changes a
key changes this file in the same pull request.

## The tables

| Table | Holds | Indexes | State |
|---|---|---|---|
| `bgucats-data` | the dataset: cats, sessions, photos, labels, the model's guesses, and the bookkeeping around them | GSI1, GSI2, GSI3 | live since phase 1a |
| `bgucats-social` | everything people do in the app: profiles, posts, polls, friends, reports, moderation | GSI1, GSI2, GSI3 | created by milestone F3 (2026-11-12), with a stream (new and old images) to the events Lambda. Empty until the milestones that write it |

Both: partition key `PK`, sort key `SK`, all strings; on-demand billing;
point-in-time recovery; deletion protection; `expiresAt` is the TTL
attribute (seconds since the epoch). Every index projects every attribute.

## `bgucats-data`

### The indexes

| Index | Partition (`…PK`) | Sort (`…SK`) | Serves |
|---|---|---|---|
| GSI1 | `SESSION#{sessionId}` | the photo's `createdAt` | every photo of a session |
| GSI2 | `STATUS#{status}`, `ENTITY#{kind}`, `VECTOR#{version}` | depends on the item, below | the labeling queue; lists of one kind of item |
| GSI3 | `CAT#{catId}` | the photo's `createdAt` | every photo of a cat, for export and templates |

An index can never be read consistently, and a list read from one may lag
a write by a moment. Nothing is decided on an item's absence from it
(`docs/notes.md`, "DynamoDB").

### The dataset

| Item | PK | SK | GSI keys | Written by | Notes |
|---|---|---|---|---|---|
| Cat | `CAT#{catId}` | `META` | GSI2 `ENTITY#CAT` / `createdAt` | admin API | `name`, `notes` (the admins' own, never sent to a user), `photoCount`; since B2 the public `bio` (≤ 280) and `usualRegionId` (an id from `web/regions.json`) |
| Session | `SESSION#{sessionId}` | `META` | app encounters: GSI2 `ENTITY#ENCOUNTER` / `{email}#{startedAt}`, or `deleted#{startedAt}` once its starter deleted their account (#135), when `startedBy` goes too | ingest; admin API (app encounters) | one encounter with one cat. `catId` is written as `null` and set by a label: a condition on "no label" must accept absent **or** null |
| Photo | `PHOTO#{photoId}` | `META` | GSI1 `SESSION#{sessionId}` / `createdAt`; GSI2 `STATUS#{status}` / `createdAt`; GSI3 `CAT#{catId}` / `createdAt` once labeled | ingest; admin API; process | on GSI2 as `STATUS#pending` from the moment it is written. Statuses: `pending`, `unlabeled`, `labeled`, `rejected`, `duplicate`. `origin = "gallery"` (since #108) on a photo picked from the phone's gallery, written with the record and never changed: it holds no `coarseLat`/`coarseLon`; absent means the camera |
| Byte-identical photo | `SHA#{sha256}` | `META` | | process | `photoId` of the first photo with these bytes. A later one is marked `duplicate` |

S3 keys follow the same IDs (spec §6.2): `raw/{sessionId}/{photoId}.{ext}`,
`derived/{photoId}/thumb-256.webp`, `derived/{photoId}/medium-1024.webp`.

### Recognition (phase 1c)

| Item | PK | SK | GSI keys | Written by | Notes |
|---|---|---|---|---|---|
| The model's guess | `SESSION#{sessionId}` | `PREDICTION#{modelVersion}` | GSI2 `ENTITY#PREDICTION` / `predictedAt` | admin API, from an admin's browser | written only while the session has no label, in one transaction with that check; the first per model version wins |
| A contributor's answer | `SESSION#{sessionId}` | `PICK` | GSI2 `ENTITY#PICK` / `sessionId` | admin API, from the contributor's phone | the latest answer wins; the labeling desk never reads it |
| A photo's vector | `PHOTO#{photoId}` | `VECTOR#{modelVersion}` | GSI2 `VECTOR#{modelVersion}` / `photoId` | admin API, from an admin's browser | ~4 KB of base64. A template only while the photo is labeled; deleted with the photo |

### People and access

| Item | PK | SK | GSI keys | Written by | Notes |
|---|---|---|---|---|---|
| Admin or collaborator | `ADMIN#{email}` | `META` | GSI2 `ENTITY#ADMIN` / `email` | admin API; Terraform (the bootstrap admin) | `role`: `admin` or `collaborator`; no role means admin. Read by the sign-up trigger and on every API call |
| A contributor | `SUBMITTER#{submitterHash}` | `PROFILE` | GSI2 `ENTITY#SUBMITTER` / first seen | ingest; admin API | when someone first showed up, on which channel, from which tracked link. The hash is salted (spec §8.5); for the app it is made from the email |
| A bot user's open session | `SUBMITTER#{submitterHash}` | `ACTIVE_SESSION` | | ingest | the 10-minute window; Done deletes it |
| A bot user's last session | `SUBMITTER#{submitterHash}` | `LAST_SESSION` | | ingest | which session a location sent just after Done belongs to |

### Bookkeeping

| Item | PK | SK | GSI keys | Written by | Notes |
|---|---|---|---|---|---|
| A Telegram message, once | `TGMSG#{chatId}_{messageId}` | `META` | | ingest | the photo this message became, so a redelivered update lands on the same records. Kept when its photo is deleted |
| An album's one reply | `MGREPLY#{mediaGroupId}` | `META` | | ingest | `expiresAt` an hour on: the first photo of an album answers for all of them |
| A bot user's rate | `RATE#{submitterHash}#{minute}` | `META` | | ingest | per-minute counter; `expiresAt` |
| A rate, in `src/common` | `RATE#{key}#{windowStart}` | `META` | | `common.limits` (not called on this table yet) | `key` is `{userId}#{action}`; `expiresAt` a day after the window. The member API will use it on `bgucats-social` |
| A day's landing-page visits | `TRAFFIC#{day}#{referral}` | `META` | GSI2 `ENTITY#TRAFFIC` / day | beacon | counters only, no visitor |
| A tracked link | `LINK#{slug}` | `META` | GSI2 `ENTITY#LINK` / `slug` | admin API | its name and the partner's own numbers |

## `bgucats-social`

**The table exists since milestone F3 (2026-11-12) and is empty:** no
route writes it yet. Each item below arrives with the milestone that
first writes it (`docs/app-plan/08-milestones.md`), and that pull request
corrects its row to what was built. Changes reach the events Lambda
through the stream filter in `src/events/filters.json`, which admits only
the kinds in `src/events/handler.py` (`KINDS`) and never what the Lambda
writes itself (`SELF_WRITTEN`); `tests/events/test_filters.py` holds the
three together.

Why a person's tag is a claim and not a label, the transactions, the
invariants and account deletion: `docs/app-plan/03-data-model.md`.

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
| User **(written since F4)** | `USER#{userId}` | `PROFILE` | `email` (never sent to others), `username`, `displayName` (the one everyone sees), `pendingName` and `pendingNameAt` (B1a: a changed name, shown to its owner alone until the events Lambda publishes it), `avatarKey` (the published profile photo's object) and `pendingAvatarKey`, `pendingAvatarAt` (B1b: a new photo, its owner's alone until the events Lambda publishes it), `phone` (D5; never sent to others), `language`, `theme`, `notifications`, `inviteCode`, `status` (`active` / `banned` / `deleting`; `banned` is written by the desk's API since B8c, with `bannedBy` and `bannedAt`; `deleting` by `DELETE /me` since B10a, with `deletingAt`, `deletingCats` (every cat's id when deletion began, for the job, which cannot read the dataset), `cognitoUser` (since B10b: the sign-in's Cognito username, from the token, for the job's first step) and `deletionStep` (the events Lambda's progress, 0 to 7; the item is deleted at the end)), `termsAcceptedAt`, `createdAt`. On `GSI2` as `ENTITY#USER` / `createdAt` |
| Sign-in lookup **(F4)** | `IDENTITY#{email}` | `META` | `userId` |
| Username lookup **(F4)** | `USERNAME#{username}` | `META` | `userId` |
| Phone lookup (D5) | `PHONE#{hmac}` | `META` | `userId`. The key is an HMAC of the number in international form, keyed with a secret from SSM, so the table holds no list of numbers that can be reversed by trying them all |
| Invite code **(F4)** | `INVITE#{code}` | `META` | `userId`. The code is random, not derived from the username |
| Friend **(written since B5a)** | `USER#{a}` | `FRIEND#{b}` | `userId` (a), `friendId` (b), `since`, `via` (`invite` / `request` / `contacts`; only `invite` is written yet), `by` (since B9: who accepted; the other one is told). Always written and deleted with its mirror (`USER#{b}` / `FRIEND#{a}`), in one transaction |
| Friend request (D4) | `USER#{to}` | `FREQ#IN#{from}` | `at`. Mirror: `USER#{from}` / `FREQ#OUT#{to}` |
| Block **(written since B8a)** | `USER#{a}` | `BLOCK#{b}` | `userId` (a), `blockedId` (b), `at`. Mirror: `USER#{b}` / `BLOCKEDBY#{a}` with `userId` (b), `blockerId` (a), `at`; always written and deleted together, in one transaction that also deletes the two `FRIEND` items. One read of a person's `BLOCK…` items is everyone a block keeps them apart from, either way |
| Device **(written since B9)** | `USER#{id}` | `DEVICE#{deviceId}` | `userId`, `deviceId`, `apnsToken`, `environment` (`production` / `development`: which of Apple's two it registered with), `updatedAt`. At most five per person; the events Lambda deletes one Apple says is gone. No route returns a token |
| Counters | `USER#{id}` | `STATS#ALL`, `STATS#{yyyy-mm}` | `catsMet`, `encounters` and `countedAt` **(written since B3b)**; on `ALL` only, **since B7a**: `points` (five for each day a cat was met and posted) and `posts` (encounters that became a post). Planned, not written: `fed`, `namesVoted`, `namesLed` **Since B7c**, on `ALL`: `fedPoints` (ten for each feeding, at most two a day), `catsFed`, `feedings`, `fedCountedAt`, set by `count_feeding` and never by the encounters' recount; the API shows `points + fedPoints` |
| A cat met **(since B3b)** | `USER#{id}` | `MET#{catId}` | `catId`, `firstDay`, `lastDay`, `days` (different days), `encounters`. Deleted when no encounter counts for the cat any more. |
| What a person gives a cat's popularity **(since B7b)** | `USER#{id}` | `METM#{yyyy-mm}#{catId}` | `catId`, `month`, `points`: one for each day they met the cat that month, five more for a day that became a post. The cat's `pop{yyyy-mm}` is the sum of these over everyone, and moves by the difference in one transaction with this item. Deleted at zero |
| Badge **(written since B7a)** | `USER#{id}` | `BADGE#{badgeId}` | `badgeId`, `at` (when it was first earned). The ids are `web/achievements.json`'s. `first-meow`, `night-owl`, `explorer` and `cat-whisperer` follow the person's encounters and are deleted if a label takes the ground from them; `name-giver` is kept once earned; `deans-list` is not stored (worked out when asked) `snack-giver` (**since B7c**) is held while the person has a feeding that stands, and deleted when an admin removed their last |
| A person's feeding **(since B7c)** | `USER#{id}` | `FED#{at}#{catId}` | The same fields as the cat's `FED#` item (below): `feedingId`, `catId`, `userId`, `at`, `day` (the Israel date, which the two-a-day rule counts by), `spotId`. Written by the member API in one transaction with the cat's; `removed` is copied here by the events Lambda when an admin removes the cat's. A person's `fedPoints`, `catsFed` and `feedings` on `STATS#ALL` are worked out again from these on every change |
| Last feeding of one cat **(since B7c)** | `USER#{id}` | `FEDCAT#{catId}` | `catId`, `feedingId`, `at`, `atS` (the same moment in seconds). The four-hour rule is this item's write condition (`atS` at least four hours old, or no item), so two phones at once cannot both log; the same `feedingId` again is answered from it. Stays when an admin removes the feeding |
| An encounter, as the app counts it **(since B3b)** | `USER#{id}` | `ENC#{sessionId}` | `userId`, `sessionId`, `proposalId` (B6: the encounter's new-cat proposal), `claimedCatId` (the pick, or the post's claim if there was no pick), `labelCatId` (the session's label, following merges), `rejected`, `day` (the Israel date the encounter began), `hour` (the Israel hour it began, 0 to 23, since B7a, for "Night Owl"; absent on older items), `regionId`, `postId`, `updatedAt` |

`ENC` is the bridge between the tables (`src/common/encounters.py`). The
capture route that records a pick writes it, and so does `POST /posts`;
the desk routes that assign, unassign, merge or reject an app encounter
set `labelCatId` and `rejected` on it from the dataset as it is then. The
events Lambda sees the change, recounts the person's `MET` and `STATS`
from all their `ENC` items, and puts the post on the label's cat. That is
how D8's "taken back if the label disagrees" happens without a stream on
the dataset table. Only for someone who has opened the app: a person with
no `IDENTITY` item gets no `ENC`, and with the `social` flag off the desk
never writes this table.

### Posts

| Item | PK | SK | Holds |
|---|---|---|---|
| Post **(since B3a)** | `POST#{postId}` | `META` | `authorId`, `sessionId`, `photoIds` (1–4, in order), `galleryPhotoIds` (those of them picked from the phone's gallery, since #108; copied from the photos when the post is written), `claimedCatId`, `proposalId`, `catId` (what is shown: the label, else the claim, else none), `text` (0–280), `regionId` (the area, only if the author shared it), `status`, `hiddenReason` (`proposal_rejected`, `reports`, `admin`, `banned`, `rejected`, `deleted`: its author deleted their account, B10a, and `authorId` and the index keys are gone), `hiddenAt`, `removedAt`, `likeCount`, `createdAt`, `visibleAt`; and, for the moment between an admin's decision and its being carried out (B8b), `modAction` (`hide` / `restore` / `remove`), `modReason`, `modBy`, `modAt`: the desk's API writes them, the events Lambda acts and removes them |
| Like **(since B3a)** | `POST#{postId}` | `LIKE#{userId}` | `at`. Written with the post's `likeCount` and the cat's `likes` in one transaction |

A post's `status`: `pending` (written, not yet checked) → `visible` |
`hidden` (waiting for an admin, or reported past the threshold) |
`removed` (by its author or an admin).

A post made with a new-cat proposal stays `pending` while the proposal is
`open`, whatever moderation says (D7: nothing about a new cat is public
before an admin approves). The events Lambda publishes it when the
proposal becomes `approved` or `merged`, under that cat, and leaves it
unpublished if the proposal is `rejected`. So a post is visible only
when all of these hold: its text passed, every photo passed, and it has
no open proposal.

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
| Public counters | `CAT#{catId}` | `PUBLIC` | `posts`, `likes`, `lastSeenAt`, `lastFedAt`, `pop{yyyy-mm}` (**since B7b**: the cat's popularity in that month, one attribute a month, e.g. `pop2026-11`. Not a map: `ADD` cannot make an entry in a map that is not there yet, and a plain attribute needs no first write. Old months are left: twelve small numbers a year), `voteTotal`, `leaderKey`, `leaderName`, `lockedName` (an admin's lock; written by the desk's API since B4b, with `lockedBy` and `lockedAt`) |
| Name option **(written since B4a)** | `CAT#{catId}` | `NAME#{nameKey}` | `catId`, `nameKey` (the name cleaned and case-folded, so "Mango" and "mango " are one option), `name` (the first spelling suggested), `votes`, `suggestedBy` (absent on the admins' own name), `status` (`pending` / `live` / `rejected` / `removed`), `createdAt`. Removed by an admin (B4b): the desk's API sets `status` to `removed` with `removedFrom` (the status it had), `removedBy`, `removedAt`; the events Lambda then sets `votes` to 0, takes them off `voteTotal` if it was live, and deletes the votes that name it |
| Vote **(written since B4a)** | `CAT#{catId}` | `VOTE#{userId}` | `catId`, `userId`, `nameKey`, `at`. One per person per cat. On `GSI2` as `FEED#{yyyy-mm}` / `{at}#V#{catId}#{userId}`, which is how a vote becomes a card in friends' feeds (written since B5a; a vote cast before it has no feed keys and makes no card) |
| Feeding (D10) **(written since B7c)** | `CAT#{catId}` | `FED#{at}#{userId}` | `feedingId` (from the phone), `catId`, `userId`, `at`, `day`, `spotId` (one of `web/regions.json`'s feeding spots, or absent), `removed` with `removedBy` and `removedAt` (the desk's API only marks; the events Lambda follows) |

There is no grade item: nobody grades a cat (D9). GPA is worked out from
`pop{yyyy-mm}` when the cats are read (`grades` in `src/app/handler.py`;
`01-product.md`, "GPA"). The numbers are kept by the events Lambda
(`count_popularity`) from the same `ENC` items as "met", so a label that
corrects an encounter corrects the cat's popularity too.

`lastFedAt` is the newest feeding that has not been removed. Removing a
feeding re-reads the partition's last `FED#` item rather than trusting a
stored "previous" value.

`nameKey` is the name normalised (NFKC, case-folded, spaces collapsed),
so "mango" and "Mango " are one option.

A cat's description, usual region, coat and status are the admin's and
live on the cat's item in `bgucats-data` (below). The member API reads
them there and adds the counters from here.

**The cat's shown name** (`shown_name` in `src/common/polls.py`, since B2;
both APIs use it):
the admin's `lockedName` if set; else the poll's `leaderName`; else the
cat's `name` in the dataset; else nothing (D6).

### Proposals, reports, moderation

| Item | PK | SK | Holds |
|---|---|---|---|
| New-cat proposal **(since B6)** | `PROPOSAL#{proposalId}` | `META` | `proposerId`, `sessionId`, `nameIdea`, `coat`, `regionId`, `traits` (`coat` and `traits` from `src/common/proposals.py`; `regionId` a campus place or `elsewhere`), `status` (`open` / `approved` / `merged` / `rejected`), `catId` (the result; an approved proposal's id **is** the new cat's id, so approving twice makes one cat), `decidedBy`, `decidedAt`. On `GSI2` as `PROPOSALS#{status}` / `createdAt` (the desk's queue), and on `GSI1` as `PROPOSER#{userId}` / `createdAt` (the proposer's own list) |
| Report **(written since B8b)** | `REPORT#{reportId}` | `META` | `reportId` (from the phone), `reporterId`, `targetType` (`post` / `user` / `avatar` / `name`), `targetId` (a post's id, a user's id, or `{catId}/{nameKey}`), `targetOwnerId`, `reason` (`src/common/reports.py`), `note` (0–280, read by admins only), `status` (`open` / `actioned` / `dismissed`), `emailedAt` (the admins were emailed), `decision`, `decidedBy`, `decidedAt`, `createdAt`. On `GSI2` as `REPORTS#{status}` / `createdAt` |
| One report per person per target **(written since B8b)** | `REPORTED#{targetType}#{targetId}` | `BY#{reporterId}` | `reporterId`, `reportId`, `at`. Written with the report in one transaction; a second report by the same person on the same thing writes nothing. Counting the partition gives "different people who reported this": at three, a post hides itself |
| Moderation run | `MOD#{kind}#{subjectId}` | `RUN#{at}` | `policy`, `model`, `mode`, `answers` (each question's probability), `outcome` (`pass` / `flag` / `block` / `error`), `acted`, `human`, `humanBy`, `humanAt`, `tokens`, `ms`. On `GSI2` as `MODQ#open` / `at` while it waits for an admin, then `MODRUN#{yyyy-mm}` / `at` |

`kind` is one of `POSTTEXT`, `NAME`, `PROPNAME`, `DISPLAYNAME`,
`USERNAME`, `AVATAR`, `PHOTO`.

### Limits

| Item | PK | SK | Holds |
|---|---|---|---|
| A person's counter for an action | `RATE#{userId}#{action}#{bucket}` | `META` | `count`, `expiresAt` |
| Decision 1 use today (K3) | `SPEND#{yyyy-mm-dd}` | `DECISIONS` | `calls`, `tokens`, `expiresAt` |
| Pushes sent to a person today **(since B9)** | `USER#{id}` | `PUSHED#{yyyy-mm-dd}` | `count` (at most five), `sent` (a set: the key of each notification, so a change delivered twice is told once), `expiresAt` (three days on). The day is UTC's |

## Who may write what

Enforced by each Lambda's own role in `infra/main`, under the ceiling of
the permissions boundary in `infra/bootstrap`:

| Lambda | `bgucats-data` |
|---|---|
| ingest | get, put, update and delete items |
| process | get, put and update items (it writes photo and `SHA#` items); query GSI1 |
| admin API | items of the table and its indexes |
| sign-up trigger | get one item (it reads `ADMIN#{email}`); its own role, so a trigger Google can cause to run cannot write |
| beacon | update `TRAFFIC#` items only (an IAM condition on the key) |
| events (since #135) | deleting an account: query GSI1 and GSI2, get `SESSION#` items, update only `submittedBy`, `startedBy`, `pickedBy` and `GSI2SK` (an IAM condition on the fields), delete `ADMIN#` items (a member's, on a condition in the code) |
| the deploy role | `ADMIN#` items only, for the bootstrap admin |

| Lambda | `bgucats-social` |
|---|---|
| events (since F3) | reads the stream; since B3a publishes a post (its status and feed keys, and `CAT#` / `PUBLIC` `posts` and `lastSeenAt`); since B10a deletes an account: every item in its `USER#` partition, its lookups, its likes, votes, feedings, ties and rate counters, and clears it from posts, proposals, name options and reports. Query, never Scan: its role has none |
| app, the member API (since F4) | items of the table and its indexes: the account (`IDENTITY#`, `USER#` / `PROFILE`, `USERNAME#`, `INVITE#`, in one transaction), the terms; since B3a posts as `pending`, likes, removal, and the cat's counters that a like or a removal changes |

The member API (`bgucats-app`, since F4) **reads** `bgucats-data` (the
allowlist today; cats and photos from B2) and never writes it:
`tests/app/test_app_role.py` reads its policy in `infra/main/app_api.tf`
and fails on any write to the dataset. The events Lambda will read it the
same way.
