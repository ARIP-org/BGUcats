# Campus Cat App — working notes for Claude Code

Authoritative specs, in order of precedence:

- `docs/recognition-design-addendum.pdf` (accepted 2026-10-28) — **authoritative for
  recognition.** Amends §10 of the spec and the phase table below.
- `docs/cat-app-design-spec.pdf` (v2 draft) — authoritative for ingest, storage,
  processing and security.

Read both before non-trivial work. This file is the short version of the
constraints that are easy to violate by reflex.

## What this project is

A mobile app for identifying, naming, and tracking campus cats — starting with the
~50 on the BGU campus, with an architecture that is deliberately not limited to
them. Browse / Identify / Name. Cats are admin-curated; there is no automated
"is this a campus cat" validation.

## The one thing to understand

**This is Face ID, for cats.** Not a classifier with one output per cat — a
detector, an aligner, an embedding network trained with metric learning, cosine
similarity against an enrolled template, and a threshold with a reject path.

The old framing ("a kNN over embeddings with a human picking from a short list"
*versus* "a model that really recognizes the cat") described one system at two
confidence levels, not two systems. Only the decision step changes as data
arrives:

| | Face ID | Cats v0 | Cats v2 |
|---|---|---|---|
| Enroll | turn your head | pan the camera around the cat | same |
| Match | embedding vs. template | embedding vs. template | same |
| Decide | accept, else passcode | accept, else **pick from 3** | accept, else pick from 3 |

The architecture shipped next month is the architecture shipped at the end. A
candidate list is not a placeholder for real recognition; it is real recognition
at a lower confidence threshold.

**Headline metric:** the fraction of queries auto-resolved at k=1 above
threshold. It starts near zero, ends near one, and every value in between is a
shippable app.

### What changed from the original spec

The spec assumed recognition had to wait for BGU data. It does not. Public
cat-identity datasets and animal-specific pretrained models are good enough to
build and measure the whole recognition path **now**, against real numbers,
before the first BGU photo is labeled. Generic embeddings (CLIP, ImageNet,
DINOv2) do cluster by category rather than individual — but models pretrained
for animal individual discrimination exist, and MegaDescriptor is one.

## Phases

| Phase | Status | Scope |
|---|---|---|
| 1a Collection + labeling infra | CURRENT | ingest, storage, processing, admin labeling |
| 1b Recognition research track | CURRENT, PARALLEL | public datasets, eval harness, zero-shot baseline |
| 2 Enrollment + burst-query UX | NEXT | video enrollment, multi-frame query, frozen v0 weights |
| 3 Fine-tuning on BGU data | CONDITIONAL | only if 1b numbers justify it |
| 4 Read path + mobile app | DEFERRED | public API, browse UI, voting |

**1b has no dependency on 1a.** It reads public datasets from disk and touches no
Lambda, no S3 bucket, and no DynamoDB table.

**The risk, stated once:** the ML track is more fun than the ingest track, and if
it eats the ingest track there is never any BGU data — the one asset here that
cannot be downloaded. 1a stays the priority; 1b is what happens when 1a is
blocked on someone else.

## Hard constraints

### Collection path (spec §10)

- **No browse, identify, voting, or polls in the app yet.** Phase 4.
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
- **The admin labeling tool is in scope for 1a.** Queue view, session grid,
  merge and reject actions. A 2,000-image backlog never gets climbed.
- **Prefer boring, inspectable choices.** Portfolio project; every decision
  should be explainable in an interview.

### Research track

- **`research/` imports nothing from `src/`.** No boto3, no AWS, no Lambda
  handler code. It must stay independently reviewable and discardable.
- **Research dependencies never enter `requirements.txt` or `src/*/requirements.txt`.**
  Torch alone would blow the 250MB Lambda package limit. `research/requirements.txt`
  is a separate world.
- **No softmax classifier over our cats, ever.** It cannot add cat #51, cannot say
  "I don't know this one", and needs retraining per cat. It would feel like
  progress and is a dead end. This is permanent, not "for now" — it is also what
  makes scaling past one campus possible at all.
- **No depth sensor.** TrueDepth and LiDAR are the tempting analogue to Face ID's
  IR projector and are a trap: wrong range, wrong subject cooperation, for a cat
  two metres away under a bush.
- **No nose-print biometrics in v1.** The published work is thin — one 70-cat,
  700-image study — and it needs a cooperative close-up we will never get.

## Recognition architecture

```
query burst (1-2 s of frames)
  → cat detector (body bbox)
  → head detector + 48 facial landmarks → align
  → two embeddings:
        E_face   aligned head crop   — geometry, facial markings
        E_coat   body crop           — coat pattern and colour
  → fused similarity vs. enrolled templates → ANN top-50
  → local-feature rerank of those 50 only (ALIKED / DISK + LightGlue)
  → accept / top-k / "new cat"
```

- **Two streams, because the failure mode is solid-colour cats.** Coat pattern
  carries nearly all the signal for a calico and nearly none for a black cat;
  face geometry carries it for the black cat. A single whole-image embedding
  blends the two *and* picks up the background.
- **Local-feature reranking is the highest-value trick available, because it
  needs no labels at all.** Too slow over the whole gallery, so it only ever
  reranks the ANN top-50.
- **Templates, not centroids.** Store several embeddings per cat. Frontal and
  profile views sit far apart in embedding space, and averaging them produces a
  vector that matches neither.
- **Enrollment is the Face ID insight:** *record ten seconds panning around the
  cat.* 30–100 frames, identity guaranteed, pose and light varied, with a free
  quality filter. This is the session-as-identity-cluster idea extended to UX.
- **Mirror it on the query side: identify a burst, not a frame.** Embed every
  frame of a 1–2 second capture and aggregate the ranked lists.

### Three axes, improving independently

| Axis | v0 | Later | Needs BGU data? |
|---|---|---|---|
| Embedding quality | zero-shot MegaDescriptor | fine-tuned on BGU + public | yes |
| Enrollment richness | multi-frame video template | same | no |
| Decision policy | top-5 human pick | top-1 auto-accept + reject | calibration only |

The right first baseline is **not** zero-shot DINOv2. It is MegaDescriptor-L-384
plus a local-feature reranker — someone else already paid for the expensive
pretraining.

## Open-set is the hard requirement

"Is this a cat I know, or a new one?" is harder than ranking, and it is the
actual product question.

- Score on similarity to the best-matching enrolled template.
- **Calibrate the threshold on held-out identities, never held-out photos.**
  Identities the model has never enrolled are the only honest proxy for cat #51.
- **Report knowns and unknowns separately** — balanced accuracy on each (BAKS and
  BAUS). An aggregate hides which half is failing.
- **Bias the threshold toward false "new cat" verdicts.** That costs an admin one
  merge, and the labeling tool already has a merge action. The opposite error
  silently corrupts the dataset and surfaces months later.

## Evaluation

- **Split by session, never by photo.** Two frames from one burst are
  near-identical; one in train and one in test makes reported accuracy fiction.
- **One listing or one source folder counts as one session.** Every photo in a
  shelter listing was taken in one sitting, against the same wall, in the same
  light. Same rule as above, different vocabulary — and the easiest way to
  accidentally report fiction when using public data.
- **Open-set from the first run.** Hold out whole identities, not just photos.
- Report top-1 and top-5 separately, plus a per-cat breakdown — an aggregate
  hides that every error is a black cat.
- **Public-data numbers are never reported as the system's accuracy.** Shelter
  portraits against a studio wall are a different world from a cat under a bench
  at dusk. Public data validates the machinery; only BGU data measures the product.

## Data model essentials

- **ULID** is the join key everywhere: DynamoDB PK, S3 key prefix, later the
  vector ID. Chosen over UUIDv4 for lexicographic time-ordering.
- **Session = one encounter with one cat = a guaranteed identity cluster.** Same
  submitter within a 10-minute idle window joins the same session; Telegram media
  groups always map to one session.
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

## Data sources

| Tier | Source | Role |
|---|---|---|
| 1 | CatIndividualImages (509 ids / 13,021 imgs, CC BY 4.0) | best single fit |
| 1 | HelloStreetCat (69 cats / 2,796 imgs) | closest domain match — uncooperative street cats |
| 1 | PetFace (257k ids) | has an unseen-individual benchmark; **non-commercial research only**, gated |
| 1 | WildlifeReID-10k | eval harness, cross-species pretraining |
| 1 | CatFLW + its detector | the alignment step |
| 2 | Petfinder / RescueGroups APIs | one listing = one individual with several photos; we ship weights, not photos |
| 3 | BGU campus | calibrates thresholds, fine-tunes, and is the only source we may quote numbers from |

## Do not

- Scrape the Instagram/Facebook archives. Meta's terms prohibit it and it is
  awkward to explain in an interview. Contact the community admins instead. (§4.3)
- Scrape any site whose terms forbid it. The Kaggle "Cat Re-Identification Image
  Dataset" is scraped from neko-jirushi.com with unclear licensing — a cautionary
  example, not a source.
- Commit cat photos, datasets, exports, model weights, or `.tfvars` — see `.gitignore`.

## Stack

**Collection:** Python 3.12 (Pillow, imagehash) · Terraform · Lambda, no VPC ·
API Gateway HTTP API · S3 + DynamoDB on-demand · secrets in SSM Parameter Store
(SecureString).

**Research:** Python 3.12 · PyTorch · timm · wildlife-datasets · kornia. Local
only; no AWS.
