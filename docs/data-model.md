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
| Session | `SESSION#{sessionId}` | `META` | app encounters: GSI2 `ENTITY#ENCOUNTER` / `{email}#{startedAt}` | ingest; admin API (app encounters) | one encounter with one cat. `catId` is written as `null` and set by a label: a condition on "no label" must accept absent **or** null |
| Photo | `PHOTO#{photoId}` | `META` | GSI1 `SESSION#{sessionId}` / `createdAt`; GSI2 `STATUS#{status}` / `createdAt`; GSI3 `CAT#{catId}` / `createdAt` once labeled | ingest; admin API; process | on GSI2 as `STATUS#pending` from the moment it is written. Statuses: `pending`, `unlabeled`, `labeled`, `rejected`, `duplicate` |
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
| User **(written since F4)** | `USER#{userId}` | `PROFILE` | `email` (never sent to others), `username`, `displayName` (the one everyone sees), `pendingName` and `pendingNameAt` (B1a: a changed name, shown to its owner alone until the events Lambda publishes it), `avatarKey` (the published profile photo's object) and `pendingAvatarKey`, `pendingAvatarAt` (B1b: a new photo, its owner's alone until the events Lambda publishes it), `phone` (D5; never sent to others), `language`, `theme`, `notifications`, `inviteCode`, `status` (`active` / `banned` / `deleting`), `termsAcceptedAt`, `createdAt`. On `GSI2` as `ENTITY#USER` / `createdAt` |
| Sign-in lookup **(F4)** | `IDENTITY#{email}` | `META` | `userId` |
| Username lookup **(F4)** | `USERNAME#{username}` | `META` | `userId` |
| Phone lookup (D5) | `PHONE#{hmac}` | `META` | `userId`. The key is an HMAC of the number in international form, keyed with a secret from SSM, so the table holds no list of numbers that can be reversed by trying them all |
| Invite code **(F4)** | `INVITE#{code}` | `META` | `userId`. The code is random, not derived from the username |
| Friend | `USER#{a}` | `FRIEND#{b}` | `since`, `via` (`invite` / `request` / `contacts`). Always written with its mirror (`USER#{b}` / `FRIEND#{a}`) |
| Friend request (D4) | `USER#{to}` | `FREQ#IN#{from}` | `at`. Mirror: `USER#{from}` / `FREQ#OUT#{to}` |
| Block | `USER#{a}` | `BLOCK#{b}` | `at`. Mirror: `USER#{b}` / `BLOCKEDBY#{a}`, so "who must not see me" is one query |
| Device | `USER#{id}` | `DEVICE#{deviceId}` | `apnsToken`, `environment`, `updatedAt` |
| Counters | `USER#{id}` | `STATS#ALL`, `STATS#{yyyy-mm}` | `catsMet`, `encounters` and `countedAt` **(written since B3b)**; `posts`, `fed`, `namesVoted`, `namesLed`; `points` on `ALL` only |
| A cat met **(since B3b)** | `USER#{id}` | `MET#{catId}` | `catId`, `firstDay`, `lastDay`, `days` (different days), `encounters`. Deleted when no encounter counts for the cat any more. (`METM#{yyyy-mm}#{catId}`, planned for the month's count, is not written: `STATS#{yyyy-mm}.catsMet` holds it) |
| Badge | `USER#{id}` | `BADGE#{badgeId}` | `at` |
| An encounter, as the app counts it **(since B3b)** | `USER#{id}` | `ENC#{sessionId}` | `userId`, `sessionId`, `proposalId` (B6: the encounter's new-cat proposal), `claimedCatId` (the pick, or the post's claim if there was no pick), `labelCatId` (the session's label, following merges), `rejected`, `day` (the Israel date the encounter began), `regionId`, `postId`, `updatedAt` |

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
| Post **(since B3a)** | `POST#{postId}` | `META` | `authorId`, `sessionId`, `photoIds` (1–4, in order), `claimedCatId`, `proposalId`, `catId` (what is shown: the label, else the claim, else none), `text` (0–280), `regionId` (the area, only if the author shared it), `status`, `hiddenReason`, `likeCount`, `createdAt`, `visibleAt` |
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
| Public counters | `CAT#{catId}` | `PUBLIC` | `posts`, `likes`, `lastSeenAt`, `lastFedAt`, `pop` (popularity per month, a map of `yyyy-mm` to a number; months older than three are dropped), `voteTotal`, `leaderKey`, `leaderName`, `lockedName` (an admin's lock, B4) |
| Name option **(written since B4a)** | `CAT#{catId}` | `NAME#{nameKey}` | `catId`, `nameKey` (the name cleaned and case-folded, so "Mango" and "mango " are one option), `name` (the first spelling suggested), `votes`, `suggestedBy` (absent on the admins' own name), `status` (`pending` / `live` / `rejected` / `removed`), `createdAt` |
| Vote **(written since B4a)** | `CAT#{catId}` | `VOTE#{userId}` | `catId`, `userId`, `nameKey`, `at`. One per person per cat. On `GSI2` as `FEED#{yyyy-mm}` / `{at}#V#{catId}#{userId}`, which is how a vote becomes a card in friends' feeds (not written yet: B4b) |
| Feeding (D10) | `CAT#{catId}` | `FED#{at}#{userId}` | `feedingId` (from the phone), `spotId`, `removed` |

There is no grade item: nobody grades a cat (D9). GPA is worked out from
`pop` when the cats are read (`01-product.md`, "GPA"). `pop` is kept by
the events Lambda from the same `ENC` items as "met", so a
label that corrects an encounter corrects the cat's popularity too.

`lastFedAt` is the newest feeding that has not been removed. Removing a
feeding re-reads the partition's last `FED#` item rather than trusting a
stored "previous" value.

`nameKey` is the name normalised (NFKC, case-folded, spaces collapsed),
so "mango" and "Mango " are one option.

A cat's description, usual region, coat and status are the admin's and
live on the cat's item in `bgucats-data` (below). The member API reads
them there and adds the counters from here.

**The cat's shown name** (`shown_name` in `src/app/handler.py`, since B2):
the admin's `lockedName` if set; else the poll's `leaderName`; else the
cat's `name` in the dataset; else nothing (D6).

### Proposals, reports, moderation

| Item | PK | SK | Holds |
|---|---|---|---|
| New-cat proposal **(since B6)** | `PROPOSAL#{proposalId}` | `META` | `proposerId`, `sessionId`, `nameIdea`, `coat`, `regionId`, `traits` (`coat` and `traits` from `src/common/proposals.py`; `regionId` a campus place or `elsewhere`), `status` (`open` / `approved` / `merged` / `rejected`), `catId` (the result; an approved proposal's id **is** the new cat's id, so approving twice makes one cat), `decidedBy`, `decidedAt`. On `GSI2` as `PROPOSALS#{status}` / `createdAt` (the desk's queue), and on `GSI1` as `PROPOSER#{userId}` / `createdAt` (the proposer's own list) |
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
| the deploy role | `ADMIN#` items only, for the bootstrap admin |

| Lambda | `bgucats-social` |
|---|---|
| events (since F3) | reads the stream; since B3a publishes a post (its status and feed keys, and `CAT#` / `PUBLIC` `posts` and `lastSeenAt`) |
| app, the member API (since F4) | items of the table and its indexes: the account (`IDENTITY#`, `USER#` / `PROFILE`, `USERNAME#`, `INVITE#`, in one transaction), the terms; since B3a posts as `pending`, likes, removal, and the cat's counters that a like or a removal changes |

The member API (`bgucats-app`, since F4) **reads** `bgucats-data` (the
allowlist today; cats and photos from B2) and never writes it:
`tests/app/test_app_role.py` reads its policy in `infra/main/app_api.tf`
and fails on any write to the dataset. The events Lambda will read it the
same way.
