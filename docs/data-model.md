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
| `bgucats-social` | everything people do in the app: profiles, posts, polls, friends, reports, moderation | GSI1, GSI2, GSI3 | **not created yet** (milestone F3). Its planned keys are in `docs/app-plan/03-data-model.md`, and move here in the pull request that creates the table |

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
| Cat | `CAT#{catId}` | `META` | GSI2 `ENTITY#CAT` / `createdAt` | admin API | name, coat, notes; `photoCount` |
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

The planned member API (`bgucats-app`) and events Lambda
(`bgucats-events`) will be able to **read** `bgucats-data` and never
write it (`docs/app-plan/02-architecture.md`).
