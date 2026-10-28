# Campus Cat App — working notes for Claude Code

Authoritative spec: `docs/cat-app-design-spec.pdf` (v2 draft). Read it before
non-trivial work. This file is the short version of the constraints that are
easy to violate by reflex.

## What this project is

A mobile app for identifying, naming, and tracking the ~50 cats on the BGU
campus. Browse / Identify / Name. Cats are admin-curated; there is no automated
"is this a campus cat" validation.

## The one thing to understand

Generic image embeddings cluster by **category**, not **individual** — two
different orange tabbies land closer together than two photos of the same cat
under different light. Individual recognition needs metric learning, which needs
many labeled photos per cat, which the app itself has to collect.

**Every downstream feature is blocked on a data problem, not a code problem.**
That is why collection is phase 1 and recognition is phase 3.

Identify does not need an exact match — it returns a short candidate list a
human picks from. Each confirmation is a labeled training example.

## Current phase: 1 — collection and labeling infrastructure

Telegram and WhatsApp bot ingestion, the installable app's Capture screen,
S3 + DynamoDB, async processing, admin labeling tool.
**No machine learning of any kind.**

| Phase | Status | Scope |
|---|---|---|
| 1 Collection + labeling infra | CURRENT | ingest, storage, processing, admin labeling |
| 2 Measurement | NEXT | held-out eval set, zero-shot DINOv2 baseline |
| 3 Fine-tuning | CONDITIONAL | triplet/ArcFace, only if phase 2 numbers justify it |
| 4 Read path + mobile app | DEFERRED | public API, browse/identify UI, voting |

## Hard constraints (spec §10)

- **Build phase 1 only.** No browse, identify, voting, or polls. No embedding model.
- **Do not attach Lambdas to a VPC.** No NAT gateway, no subnets, no security
  groups. Lambda outside a VPC has full internet access; S3, DynamoDB and the
  Telegram API are all public endpoints. (§8.1)
- **The ingest handler must not process images.** Fetch, store, record, respond.
  Telegram times out webhooks and a slow handler means lost submissions. All
  processing is triggered by the S3 event.
- **Use the exact key formats in spec §6.2 and §6.3.** The ID-as-join-key
  property depends on them.
- **Every write is idempotent on the ULID.** Write order: DynamoDB record as
  `pending`, then S3, then flip to `unlabeled`. A record marked ready whose
  object never landed is a silent failure that surfaces months later.
- **The admin labeling tool is in scope for phase 1.** Queue view, session grid,
  merge and reject actions. Build it in week one — a 2,000-image backlog never
  gets climbed.
- **Prefer boring, inspectable choices.** Portfolio project; every decision
  should be explainable in an interview.

## The app (web/) — labeling desk and Capture, one PWA

The admin tool is installable ("Add to Home Screen") and is also how invited
collaborators photograph cats. It **complements** the bots, never replaces
them: Telegram and WhatsApp keep working unchanged, and the app is a third
channel (`channel = "app"`) into the same table, bucket and process Lambda.

- **Two roles on the one allowlist item** (`ADMIN#{email}`, field `role`).
  `admin` = everything. `collaborator` = Capture, browse cats, and assign queue
  sessions to cats that *already exist*. No deleting, merging, creating or
  renaming cats, stats, or people. **No role field means admin**, so the
  Terraform bootstrap item and `make admin-add` keep full access. The API
  enforces this per route (`ROUTES` in `src/admin/handler.py`, last column);
  the UI only hides what would be refused.
- **An encounter is a Session opened deliberately** ("Start an encounter" …
  "Done"), so it is an identity cluster by construction.
- **Same write order as the bots, split across calls:** record as `pending`
  (`POST /api/encounters/{id}/media`) → the phone uploads to
  `raw/{sessionId}/{photoId}.{ext}` with a presigned POST that pins key, type
  and size → `POST /api/photos/{id}/complete` confirms the object and sniffs
  its magic bytes before flipping to `unlabeled`. The status flip is
  conditional on `pending`, so a duplicate verdict from the process Lambda
  is never overwritten.
- **IDs are ULIDs minted on the phone**, so the offline outbox (web/outbox.js)
  can retry anything and land on the same records.
- **Location comes from the phone's GPS at the moment of capture**, with its
  accuracy (`locationSource = "app-gps"`, `locationAccuracyM`), rounded to
  3 decimals like everything else.
- **The service worker (web/sw.js) is network-first** and never touches
  `/api/`, photos or other origins — the distribution's no-caching rule still
  means a deploy reaches everyone on their next load.

## Data model essentials

- **ULID** is the join key everywhere: DynamoDB PK, S3 key prefix, later the
  vector ID. Chosen over UUIDv4 for lexicographic time-ordering.
- **Session = one encounter with one cat = a guaranteed identity cluster.** This
  is the highest-leverage decision in the collection plan. Same submitter within
  a 10-minute idle window joins the same session; Telegram media groups always
  map to one session.
- S3 layout:
  ```
  raw/{sessionId}/{photoId}.{ext}        original, write-once, never mutated
  derived/{photoId}/thumb-256.webp
  derived/{photoId}/medium-1024.webp
  exports/{datasetVersion}/manifest.json
  exports/{datasetVersion}/images/...
  ```
- Single DynamoDB table, three GSIs: photos-in-session, labeling queue by
  status, photos-of-a-cat for export.

## Processing rules

- pHash + SHA-256. Near-duplicates are **flagged, not silently dropped** — a
  burst of similar frames is legitimate.
- Derivatives: 256px thumbnail, 1024px medium, WebP.
- EXIF: extract capture timestamp and GPS into the record, then **strip all EXIF
  from every derivative**. Store location rounded to ~100m — it must not reveal
  precisely where a contributor was standing.

## Evaluation (built during phase 1, not phase 2)

**Split by session, never by photo.** Two frames from one burst are
near-identical; one in train and one in test makes reported accuracy fiction.
Report top-1 and top-5 recall separately plus a per-cat breakdown — an aggregate
hides that all errors concentrate on the tabbies.

## Security (§8.5)

- Validate the `X-Telegram-Bot-Api-Secret-Token` header on every webhook call.
  Without it the endpoint is an open upload to anyone who finds the URL.
- Cap file size; validate content type by magic bytes, not filename extension.
- Rate-limit per submitter hash at the Lambda level.
- Salt the submitter hash, salt in SSM. Storing raw Telegram user IDs makes the
  table a personal-data store for no benefit.

## Stack

Python 3.12 (Pillow, imagehash) · Terraform · Lambda, no VPC · API Gateway HTTP
API · S3 + DynamoDB on-demand · secrets in SSM Parameter Store (SecureString).

## Do not

- Scrape the Instagram/Facebook archives. Meta's terms prohibit it and it is
  awkward to explain in an interview. Contact the community admins instead. (§4.3)
- Commit cat photos, datasets, exports, or `.tfvars` — see `.gitignore`.
