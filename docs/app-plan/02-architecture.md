# Architecture

How the app is built on what exists. The short version: one new table,
two new Lambdas, one new kind of AWS resource, no VPC, no new AWS
service.

## The database question

The owner's expectation: a social app needs a relational database, and
that is awkward for a serverless project. **The recommendation is not to
add one** (decision A1). The reasoning, so it can be checked rather than
believed:

### Every query the prototype makes

| What a screen needs | How it is read | Cost |
|---|---|---|
| My profile, my settings, my counters | one item by key | 1 read |
| A person by email, by username, by invite code, by phone | one lookup item by key each | 1 read |
| My friends | one partition: `USER#me`, keys starting `FRIEND#` | 1 query |
| Is this person my friend / blocked | one item by key | 1 read |
| "2 mutual friends" | two friend lists, intersected in the Lambda | 2 queries |
| The feed, newest first | an index partition per month, read backwards | 1 query per page |
| The feed for friends only (if D3 says so) | the same query, kept if the author is in my friend set | 1–3 queries per page |
| Which of these 20 posts did I like | a batch read of 20 keys | 1 batch |
| A post's like count | a number on the post, changed in the same transaction as the like | 0 extra |
| My posts; a friend's posts | an index partition per author | 1 query |
| A cat's posts, count, likes, last seen | an index partition per cat; counters on the cat's public item | 1 query, 1 read |
| A cat's name poll with counts | one partition: `CAT#id`, keys starting `NAME#` | 1 query |
| My vote on this cat | one item by key | 1 read |
| Friends who voted for each name | the cat's votes (one query), kept if the voter is a friend | 1 query |
| The podium and "found N cats", month or all time | a batch read of my friends' counters, sorted in the Lambda | 1 batch |
| The gallery, any sort order; search | every cat once (about fifty), sorted on the phone | 1 query, cached |
| The map | the same cats, grouped by region on the phone | 0 extra |
| Badges, points, level | one partition: `USER#me` | 1 query |
| Contacts that are on the app | a batch read of hashed numbers | 1 batch per 100 |
| The admin's queues | an index partition per queue | 1 query |

Nothing in that table is a join the database must do. Where two lists
meet (mutual friends, friends who voted, a friends-only feed), both lists
are short and bounded by the size of one campus, and the Lambda
intersects them in memory.

### What a relational database would cost here

| Option | Why not |
|---|---|
| RDS, or Aurora Serverless v2 kept awake | Lives in a VPC. Lambdas would join it (spec §8.1 forbids it) or use the Data API. The always-on minimum is roughly the $40 at which the budget stops the app |
| Aurora Serverless v2, paused when idle | Wakes in about 15 seconds. A campus app is idle most of the night and between classes; the first person back waits |
| **Aurora DSQL** | The one that fits: no VPC, IAM sign-in, scales to zero with no wake-up, a free allowance. Still: a new service on the organization's allowlist, a new resource type, a database driver in every Lambda, **schema migrations as a new deploy step with no hand deploys allowed**, tests that can no longer run on moto alone, and a second source of truth whose rows point at photos in the first |

### What DynamoDB costs here, said honestly

- Every access pattern is designed up front. A new screen with a new
  query may need a new key or a backfill. That is why `03-data-model.md`
  exists and must be kept true.
- No ad hoc questions. "How many people voted and never posted?" is a
  script over an export, not a query. For the admin's Stats this is how
  it already works.
- Counters are kept by transactions and by the events Lambda, not
  computed. A bug there shows as a wrong number until a recount.
- The friends-only feed is the weak spot. It is fine for a campus; at
  tens of thousands of accounts it needs a per-person feed copy.

### When to revisit

Search over post text; weekly reports nobody predicted; a friends-only
feed for more than about ten thousand accounts; several campuses with
shared statistics. Then: Aurora DSQL beside the tables, fed from the
stream, for reading only. Not before.

## The parts

```
 iPhone app (native/, Capacitor)          PWA / desktop browser
   web/ packed inside                       web/ from CloudFront
        │                                        │
        └────────────── HTTPS, Cognito token ────┘
                             │
                  API Gateway (HTTP API, JWT authorizer)
                    │                         │
          ANY /api/{proxy+}            ANY /api/v1/{proxy+}
                    │                         │
        bgucats-admin (exists)         bgucats-app (new)
        desk, capture, re-rank         the member API
          │        │      │              │           │
          │        │      └─ Decision 1  │ read      │ read/write
     read/write    │         (re-rank)   │           │
          ▼        ▼                     ▼           ▼
     bgucats-data  S3 media ◄──── bgucats-data   bgucats-social (new)
     (dataset)     raw/ derived/  (cats, photos:      │ stream
          ▲        avatars/        read only)         ▼
          │                                   bgucats-events (new)
     bgucats-process (exists)                 moderation, counters,
     S3 event: hash, derivatives              badges, push, deletion
                                                │        │       │
                                           Decision 1   APNs   SNS alerts
                                           (Google)    (Apple)  (email)
```

Unchanged: the ingest Lambda and the bot, the process Lambda, the beacon,
the landing site, sign-in through Cognito and Google, the recognition
model in the browser, the outbox.

## The three API-side Lambdas

| | `bgucats-admin` (exists) | `bgucats-app` (new) | `bgucats-events` (new) |
|---|---|---|---|
| Answers | `/api/*` except `/api/v1/*` | `/api/v1/*` | nothing: fed by the social table's stream |
| For | the labeling desk; the capture routes; the new desk queues; re-rank | everything a member does that is not an upload | what happens after a write |
| Code | `src/admin/` | `src/app/` | `src/events/` |
| `bgucats-data` | read and write | **read only** (cats, photos, sessions) | **read only** |
| `bgucats-social` | read and write (queues, bans) | read and write | read and write |
| Media bucket | as today | sign GETs; sign avatar uploads | read derivatives |
| Secrets | + the Gemini key (re-rank) | none | the Gemini key, the APNs key |
| Calls out | Google (re-rank only) | nobody | Google, Apple |
| Size | as today | 512 MB, 15 s | 512 MB, 60 s |

Why a second API Lambda rather than more routes in the first: the
existing one can delete photos and merge sessions. A member-facing
handler with a role that cannot write the dataset at all is a wall, not a
promise. API Gateway routes the more specific path (`/api/v1/`) to it;
the `OPTIONS` route without an authorizer is repeated for it
(`docs/notes.md`, "The iPhone app").

**Shared code:** `src/common/` (reading the caller, responses, table
helpers, ULIDs, rate limits, input cleaning, the Decisions client). Each
function's package is built by the `Makefile` from its own folder; F2
makes every build copy `common/` in as well, and keeps the zips
byte-stable (`docs/notes.md`, "The same source must give the same zip").

**Who is the caller:** the token's email claim, as today. The member API
maps it to a user id through one strongly consistent read
(`IDENTITY#{email}`), creating the user on their first call. The existing
handler's `_require_member` learns a third role: on the allowlist → admin
or collaborator as today; otherwise an active user → `member`. Members
reach the capture routes and nothing else there.

## What happens after a write: the events Lambda

Decision A3. The social table has a stream; `bgucats-events` reads it
through an event source mapping whose **filter** passes only the kinds of
item that have consequences (posts, names, votes, likes, friend edges,
proposals, reports, users). One dispatcher, small handlers:

| On | Does |
|---|---|
| a post, name, proposal, profile name or avatar written as `pending` | moderation (`06-moderation.md`), then sets it `visible` or sends it to the queue |
| a post becoming `visible` | counters on the cat and the author; "met"; points and badges; push to friends |
| a vote | recount the leader; "Name Giver" |
| a friend edge | push; counters |
| a report | email through the alerts topic; hide at the threshold (D15) |
| a user set to `deleting` | the deletion job (`03-data-model.md`, "Deleting an account") |

Rules for every handler:

- **Idempotent.** A stream delivers at least once. Each handler checks
  the state it is about to make before making it, and writes with
  conditions.
- **Never blocks a person.** The request that wrote the item has already
  answered.
- **Fails loudly.** A record that fails is retried three times, then the
  mapping sends it to the alerts topic and moves on; the item stays
  `pending`, which the desk's moderation queue lists after ten minutes
  with a "run again" button. An alarm watches the stream's iterator age.
- **No schedules.** Nothing here needs a timer; the organization's
  allowlist keeps EventBridge off and this plan does not ask to open it.

## Flags

Per account, in `infra/main`'s settings; given to the Lambdas as
environment variables and to the client in `GET /api/v1/me` (the iPhone
app carries a packed copy of `web/`, so a flag read from a packed file
would need a new build to change).

| Flag | Values | Production until L3 |
|---|---|---|
| `social` | on / off. Off: `/api/v1/*` answers 404 and the client is today's app | off |
| `signup_policy` | `allowlist` / `domain` / `open` | `allowlist` |
| `feed_scope` | `campus` / `friends` (D3) | — |
| `friend_requests` | on / off (D4) | — |
| `contacts` | on / off (D5) | off |
| `proposals` | on / off | — |
| `grades`, `feedings` | on / off (D9, D10) | off |
| `push` | on / off | off |
| `capture_burst` | on / off (D12) | off |
| `moderation_mode` | `off` / `shadow` / `enforce` | `off` |
| `hold_unchecked` | on / off: does an item nothing has decided wait for an admin | on |
| `rerank_mode` | `off` / `shadow` / `live` | `off` |

`moderation_mode = off` with `hold_unchecked` on means no call to Google,
and every item waits for an admin. It is the safe position, not the open
one. How the two settings combine: `06-moderation.md`, "Two settings".

**The rule that keeps production promotable (P2):** with `social` off,
no request reaches new code, the stream's Lambda sees no records, and the
desk, Capture and the bot pass their existing tests unchanged.

## What the guardrails must learn

Milestone F1, applied by the owner (O4). One pull request, so the owner
applies once per account rather than once per feature.

**`infra/main/allowed-resource-types.txt`:** one line,
`aws_lambda_event_source_mapping`. The second table and the new Lambdas
are kinds already on the list.

**`infra/bootstrap`, the deploy role:**

- the table statements cover `table/bgucats-social` as well as
  `bgucats-data`;
- event source mappings for `bgucats-*` functions: create, update,
  delete, get, list, tag;
- confirm, rather than assume, that the Lambda and role statements match
  the new names (`bgucats-app`, `bgucats-events`, their roles) and that
  the inline policies stay under the 10,240-character limit: the role is
  past 8,500 (`docs/notes.md`), so this is probably the change that moves
  some statements to a managed policy.

**`infra/bootstrap`, the Lambda permissions boundary** (the most any
Lambda can have, whatever a pull request writes):

- items of `bgucats-social` and its indexes;
- reading that table's stream (`DescribeStream`, `GetShardIterator`,
  `GetRecords`, `ListStreams`);
- `sns:Publish` on the alerts topic only;
- for account deletion: `cognito-idp:AdminDeleteUser` and
  `AdminUserGlobalSignOut` on this account's user pool;
- `ssm:GetParameter(s)` on `/bgucats/*` is already there: confirm it
  covers the two new secret names.

**`infra/org`, the service allowlist:** nothing for F1. Every service
used is already allowed. Later, each its own owner step: `acm` for a
custom domain (A6, O9); the SMS spending limit if D5 chooses codes (O17).

**`scripts/check_plan.py`:** already refuses a provisioned table and an
oversized Lambda for any table or function; add tests that say so for
the new ones.

**`infra/main/alarms.tf`:** the two new functions join
`alarmed_functions` in the pull request that creates them; one new alarm
on the events Lambda's iterator age.

**`.github/CODEOWNERS`:** already covers `infra/bootstrap` and
`infra/org`.

## Secrets

Both set by the owner with `infra/scripts/set-secret.sh`, which gains two
names; Terraform only names the parameters.

| Parameter | Used by | Step |
|---|---|---|
| `/bgucats/gemini-api-key` | events (moderation), admin (re-rank) | O5 |
| `/bgucats/apns-auth-key` | events (push) | O7 |

Not secrets, so ordinary settings: the APNs Key ID, the Team ID, the
bundle id, the Decisions model id.

## Storage

The media bucket gains one prefix. Everything else in spec §6.2 stands.

```
avatars/{userId}/{avatarId}.jpg     a profile photo, at most 512 px, at most 200 KB
```

The phone scales and re-encodes the picture before uploading (which also
drops its EXIF), uploads with a presigned POST that pins the key, the
type and the size, and confirms; the API checks the magic bytes and
refuses a file that still carries an EXIF block. No Lambda resizes it.
An avatar is shown to others only after moderation.

Post photos are the encounter's photos: `raw/` and `derived/`, written by
the capture routes and the process Lambda exactly as today.

## Abuse and limits

API Gateway's stage throttle is the outer wall. Inside, a per-person
counter per action in the social table (the bot's `RATE#` pattern, with
the table's TTL):

| Action | Limit |
|---|---|
| posts | 20 a day |
| name suggestions | 10 a day, 3 per cat |
| votes | 60 an hour |
| likes | 300 an hour |
| reports | 20 a day |
| friend requests | 30 a day |
| invite accepts | 20 a day |
| contact matching | 2 calls a day, 2,000 numbers each |
| avatar changes | 5 a day |
| re-rank | 60 a day per person; a daily ceiling per account (K3) |

Contact matching is the sensitive one: without a tight limit it answers
"is this phone number registered?" for anyone who asks.

Every text field is cleaned on the server before it is stored: Unicode
normalised (NFKC), control and zero-width characters and direction
overrides removed (they matter with Hebrew and Arabic), whitespace
collapsed, length checked in characters. The client's `maxlength` is a
convenience, not a check.

A banned user (`status = banned`) is refused on every write by both APIs.

## What it costs

Estimates, to be replaced by measurements at L2. Today production costs
about two cents a month (`docs/notes.md`, "Money").

| | Internal beta, 50 people | A campus, 1,000 active |
|---|---|---|
| DynamoDB, Lambda, API Gateway | inside the free allowances | about $2 a month |
| S3, photo originals | cents | grows by roughly $1 a month for every month of 200 posts a day; originals are 2–4 MB each and are kept |
| S3, photos sent to phones | free allowance | about $3 a month once past 100 GB out |
| Decision 1 | cents | at most $2 a day by the ceiling (K3); expected far less |
| Apple push | free | free |

The first lever if it grows: serve photos through CloudFront instead of
straight from S3 (its free allowance is ten times larger). That needs
signed URLs from CloudFront and two new resource types, so it is a
decision for then, not now. The second: storage class for old originals,
which spec §6.2 already describes for derivatives.

The $10 budget email will arrive some months into a campus-wide launch
from storage alone. That is expected, and P1 says to revisit the budget
numbers at L2 rather than be surprised.

## Staging and production

Staging gets every merge, has every flag on as soon as its feature
exists, keeps its allowlist for sign-in, its own Gemini key, and never
holds real contributor photos: its content is the seed script's made-up
campus, which F3 extends with people, posts, votes and friends.

Production gets the code dark (P2) and turns on at L3.

The iPhone builds talk to staging until L3 (`ios.yml`, `SITE`). Pointing
a build at production is one line there and an owner's decision.
