# Deploying `recognition-labeling` — the model in the labeling desk

A runbook for one deploy, written for whoever runs it next, by hand or with
Claude Code in the codespace.

## What is being deployed

`recognition-labeling` is `app-preprod` (what production runs today) plus:

- **research/** merged in from the research branch — never deployed, it only
  rides along in the repo.
- **The model in the labeling desk** (phase 1c, CLAUDE.md "Recognition in the
  labeling desk"): when an admin opens the Queue, the browser downloads the
  model once (~40 MB), learns the labeled cats, and records a ranked guess for
  each queue session before anyone labels it. The guess is revealed only
  after labeling. Stats gains a "Recognition model" panel: the live record,
  and a replay over labeled sessions.
- **Cat guesses in Capture**, opt-in for everyone who uses Capture: after a
  photo the phone asks "Is it one of these?" with three cats, plus "None of
  these" and "Not sure". The answer goes through the outbox and is kept
  apart from the label (the labeling desk never shows it). Stats shows
  these answers scored against the admins' labels.
- **Shared vectors**: an admin's browser uploads the vectors it computes, so
  contributors' phones download ~1 MB of templates instead of embedding
  every labeled photo.
- **API routes**: `GET /api/recognition/gallery`,
  `GET /api/recognition/predictions`, `POST /api/sessions/{id}/prediction`,
  `POST /api/recognition/vectors` (admins); `GET /api/recognition/vectors`
  and `POST /api/encounters/{id}/pick` (any member, own encounter only).
  New items are `SESSION#{id}` / `PREDICTION#{version}`, `SESSION#{id}` /
  `PICK` and `PHOTO#{id}` / `VECTOR#{version}`; nothing existing is
  rewritten. Deleting a photo now also deletes its vectors.

The bots, the process Lambda, the landing page and the data model are not
changed.

## 1. Check out and test

```bash
git fetch origin && git checkout recognition-labeling && git pull
make lint && make test
```

## 2. Build and publish the model

The export needs the research environment, never the root one:

```bash
python -m venv ~/.venvs/research && . ~/.venvs/research/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install timm==1.0.30 onnx==1.23.2 onnxruntime==1.31.1 onnxscript==0.7.2 Pillow numpy
make model-export
deactivate
```

Then, with the normal environment:

```bash
make model-publish
```

It prints the manifest and "a device downloads about 39.7 MB". Publishing
first is safe: nothing loads `model/` until the new app.js is deployed.
The objects are outside Terraform on purpose (built, not committed).

## 3. Plan, and read it

```bash
make tf-plan
```

Expected, and nothing else:

| Resource | Change |
|---|---|
| `aws_s3_bucket_cors_configuration.media` | update in place: `allowed_methods` gains `GET` (the canvas must read a photo's pixels) |
| `aws_s3_object.web["recognition.js"]` | create |
| `aws_s3_object.web["app.js"]`, `["capture.js"]`, `["outbox.js"]`, `["sw.js"]`, `["styles.css"]` | update in place |
| `aws_lambda_function.admin`, `aws_lambda_function.admin_presignup` | update in place: new code (they share one zip) |

Other Lambdas may show a code update from a rebuilt zip of identical source;
harmless (see the memory note on non-reproducible zips).

**Stop if the plan shows anything to destroy or replace**, or touches
`model/` objects, Cognito, SSM, the DynamoDB table, CloudFront or API Gateway.

## 4. Apply and check

```bash
make tf-apply
```

On a phone with the installed app, as an admin:

1. Queue: a dashed line says "Model: downloading the model …", then
   "learning the cats …", then "knows N cats from M photos". The first time
   takes a few minutes; later visits are instant.
2. Label a session: a second toast says what the model had guessed.
3. Stats → Recognition model: the live record shows that session; "Replay on
   labeled sessions" gives the leave-one-session-out numbers.

4. **Share the vectors:** that first Queue visit also uploads the vectors
   ("sharing what it learned …"). Until an admin has done this once,
   contributors' guesses stay hidden — their phones have nothing to match.
5. As a collaborator (or in Capture as an admin): accept "Let the app guess
   the cat?", start an encounter, take a photo of a known cat. "Is it one of
   these?" appears within a few seconds; answer it. Stats → Recognition model
   → "Contributors" shows it once the encounter is labeled.

If the strip says "model fetch failed" or a photo fetch fails, check the
media bucket CORS rule first.

## Rollback

```bash
git checkout app-preprod && make tf-apply
```

The `model/` objects and the prediction items can stay: nothing in
`app-preprod` reads them.

---

## Follow-up: uploads that never arrived (2026-10-29)

A small change on the same branch, deployed with the same commands
(`make lint && make test`, `make tf-plan`, `make tf-apply`). No model
publish, no new resources.

**Why.** On 2026-08-24, Telegram's `getFile` stalled past the 8-second
timeout five times in a row. urllib raised a bare `TimeoutError`, not a
`URLError`, so the handler fell through to its catch-all and acknowledged
each update. Five photos were lost: each record stayed `pending` (the write
order did its job), but nothing ever looked at `pending` records, and the
sender never heard about it. The logs (`/aws/lambda/bgucats-ingest`,
20:03–20:06 UTC) show it, and nothing like it has happened since.

**What changes:**

- **Ingest (Telegram and WhatsApp):** a timed-out or failed fetch now
  counts as a failed download (`OSError`, which covers both), and the bot
  replies "… Could you send it again?". Neither platform redelivers an
  update we acknowledge, so the person has to be the retry.
- **Pending records are on the status index** (`GSI2PK = STATUS#pending`)
  from the moment they are written, in the bots and in the app's
  `POST /api/encounters/{id}/media`. The flip to `unlabeled` already
  overwrote GSI2PK, so nothing else changes.
- **Stats → Bot health** gains "Uploads that never arrived": records still
  `pending` an hour after they were written, oldest first, with channel and
  photo ID (`stalled` in `GET /api/insights`).
- **The process Lambda skips an object with no photo record.** One was
  copied into `raw/` by hand on 2026-08-28 and processing it invented a
  half-built `PHOTO#01TESTVIDEODIAGNOSTICTEST1` record.

**Expected plan:** code updates to `aws_lambda_function.ingest`,
`.whatsapp`, `.process`, `.admin` and `.admin_presignup`, and
`aws_s3_object.web["app.js"]`. Nothing to create, destroy or replace.

**After apply:** open Stats. "Uploads that never arrived" reads 0. The five
old records predate the index, so they don't show up there (see "Old
records" below). Send the Telegram bot a photo: it should still say
"Got it!".

**Old records, cleaned by hand.** These are leftovers, not bugs. Back each
item up (`aws dynamodb get-item … > backup.json`) before deleting it:

- `PHOTO#01TESTVIDEODIAGNOSTICTEST1` and the `SHA#afda0768…` item that
  claims its hash — the diagnostic upload above.
- The five stuck photos, `PHOTO#01M0TNX24R01TCZR86BMS483XY`,
  `01M0TNXSJ40FHA8SPQPASZM19T`, `01M0TNYC1CXCX3MNYQ5A4A25QX`,
  `01M0TP1SK1J6NN3CDEJ78ET1NH`, `01M0TP26TX0FFG7Z51NAVJ9RHQ`. No S3 object
  exists for any of them, and the Telegram file IDs were never stored, so
  they cannot be recovered. Either delete them (and mark their four sessions
  the way Reject does: `rejectedAt`, `photoCount = 0`), or set
  `GSI2PK = STATUS#pending, GSI2SK = createdAt` on them so Stats lists them.
  Leave their `TGMSG#` items in place, as Reject does.

Sessions with no photos are **not** leftovers. Most were left empty on
purpose by Reject (they carry `rejectedAt`). The rest are encounters that
were opened and closed without a photo, and one is still a bot's
`LAST_SESSION` pointer. Keep them.

**Rollback:** check out the previous commit and run `make tf-apply`. The
`STATUS#pending` index entries are harmless to the old code. Its
`GET /api/stats` already counted `STATUS#pending` and simply always got 0.

The follow-up above was deployed on 2026-10-29, together with the fix below.

---

## Fix: Capture uploads stalled, and the model could not write (2026-10-29)

Deployed on 2026-10-29 (`make lint && make test`, plan, apply). The plan was
11 in-place updates: the admin role's policy, every Lambda's code (only
admin and the follow-up above really changed; the rest is zip noise), and
`app.js`, `capture.js`, `outbox.js`, `recognition.js`. No CloudFront
invalidation: the admin site is not cached.

**What went wrong.** An admin took 48 photos in Capture, and an hour later
they still said "uploading…". The API had received the encounters but not
one `POST /media`, and returned no 4xx or 5xx for them (API Gateway
metrics). So the outbox stalled on the phone, before its first call for a
photo. It re-saved every item, bytes included, to mark it "uploading". That
write, or any request that hung, stopped the whole pass. Nothing timed out,
and the screen gave no reason. Safari is known to refuse to store a Blob it
has just read out of IndexedDB, so that is the likely trigger. We could not
confirm it without the phone.

Separately, `POST /recognition/vectors` returned 500 (`AccessDenied` on
`dynamodb:BatchWriteItem`), so no vectors were ever shared and Capture's
guesses were always hidden. Blind queue guesses would have failed the same
way, on `dynamodb:ConditionCheckItem` (a transaction's ConditionCheck step
is authorized on its own). None had been tried yet: the queue was empty,
and an empty queue never started the model.

**What changed:**

- **Outbox (web/outbox.js):** a photo's bytes are written once and never
  again. Its state goes in a new `states` store (IndexedDB v2); items saved
  by v1 are read as they are. Every API call times out after 35 s and an S3
  upload after 180 s. A failure that belongs to one photo (a 5xx, a refused
  upload) no longer blocks the photos behind it. An S3 4xx marks the photo
  failed, with "Try again". Capture shows the last error ("Retrying — last
  try: …").
- **Encounters are created on the server with their first photo.** One that
  is opened and closed empty never reaches the API. `GET /api/encounters`
  leaves out encounters with no files.
- **IAM:** the admin role gets `BatchWriteItem` and `ConditionCheckItem`.
- **The Queue runs the model even when empty**, so an admin's visit always
  learns and shares the cats. Capture says "The app doesn't know any cats
  yet" instead of hiding the panel. An admin's own learned gallery is no
  longer replaced by the shared copy.
- **Caching:** presigned photo URLs carry
  `response-cache-control=private, max-age=86400, immutable`. The app reuses
  the first URL it saw for each object until five minutes before it
  expires, and keeps that across launches (localStorage `bgucats.photoUrls`).
  A screen's GETs are reused for 15 s. After that, the screen shows the last
  answer at once and redraws only if a refresh changed something. Any action
  the person takes clears that memory.

**Verified, headless (real app, stub API answered by the live Lambda's
GETs):**
- An old v1 outbox seeded with 48 stuck photos uploaded 47 of them within 4
  s of the new app loading. The one seeded as failed waited for "Try again".
- The empty queue learned 20 cats from 228 photos and shared 10 vector
  batches. Capture then asked "Is it one of these?" and recorded the pick.
- After the first visit, switching between screens took 0.02–0.06 s and
  downloaded no photos.

**Rollback:** check out the previous commit and run `make tf-apply`. An
IndexedDB opened at v2 still works with the v1 code: v1 opens without a
version, ignores the `states` store, and reads every item as queued.

---

## The model's guess in plain sight, and guesses that never recorded (2026-10-29)

**Asked for:** the admin wanted the model's guesses easy to see. Until now
the guess showed only after labeling, as a toast that disappeared within
seconds. The admin decided that seeing it first does not sway their
judgment.

**What changes:**

- **Queue cards** show "Model's guess" between the header and the photos:
  the top three, each with its cover, rank and cosine similarity. #1 is
  emphasised. It redraws as the model reaches the session ("getting ready…",
  "looking at these photos…"). Tapping a guess opens the picker.
- **The picker** shows the same three above the full list. One tap labels,
  like any tile.
- After a label, the verdict toast ("The model's first guess was … ✓")
  stays for 9 s instead of 3.5 s.
- **Fix:** `POST /api/sessions/{id}/prediction` refused every real session
  with 409 "already labeled". Bots and the app write sessions with
  `catId = null`, a null attribute *exists*, and the transaction's check was
  `attribute_not_exists(catId)`. It is now `attribute_not_exists(catId) OR
  attribute_type(catId, :null)`. The test fixture had left `catId` out, which
  is why the tests never caught it. A new test writes it as null. In
  production, 0 predictions had been recorded, and the five app sessions
  labeled at 13:10–13:13 were each refused once (API Gateway 4xx).

**What this means for the numbers:** the model's live record stays honest,
because each guess is still recorded before the label exists. Labels made
from now on, though, may lean on the guess. Lookalikes are where that would
show. Keep this in mind before using these labels to calibrate thresholds or
to fine-tune.

**Verified, headless (live Lambda GETs, a stub queue of three real
sessions, phone and desktop widths):** each card shows three guesses and
the picker matches them. The prediction POST happens before the assign, and
one tap in the picker labels. Then the toast reads "The model's first guess
was … too ✓".

**Expected plan:** code updates to `aws_lambda_function.admin` and
`.admin_presignup` (plus zip noise on the others), and
`aws_s3_object.web["app.js"]`, `["recognition.js"]`, `["styles.css"]`.
