# Deploying

`main` is production. Every change reaches AWS the same way:

```
short-lived branch → pull request → CI (ruff, pytest, terraform plan)
  → the owner reads the plan and merges → push to main
  → .github/workflows/deploy.yml (environment "production", OIDC deploy role)
  → terraform plan → terraform apply → CloudFront invalidation if the landing page changed
```

Nobody runs `make tf-apply` by hand any more, and no machine holds an AWS
access key. The roles, and why there are three of them: `infra/README.md`.
The owner's one-time setup: `docs/MANUAL_STEPS.md`.

## What the deploy job does

`deploy.yml` runs on every push to `main`, and by hand from the Actions tab
(*Deploy → Run workflow*). One run at a time (`concurrency: deploy-production`),
and a run that has started is never cancelled: a half-finished apply is worse
than a late one.

1. `make lint && make test`: the same checks as CI, again on the merged code.
2. `make build`: the Lambda zips.
3. `terraform plan -out=tfplan` on `infra/main`. It needs no secrets: the
   bot's and Google's live in AWS only, outside Terraform ("Secrets" below).
4. `terraform apply tfplan`: exactly the plan above, nothing recomputed.
5. If the plan changed any `aws_s3_object.site[...]`: `make site-invalidate`.
   The landing page is cached for up to a day; the admin app is not cached,
   so it never needs this.

`workflow_dispatch` has a `plan_only` input that stops after step 3. It is
how the pipeline was proven before its first apply. Applies have been on
since 2026-10-30 (`PLAN_ONLY_ON_PUSH: "false"`): every merge to `main`
applies.

## Reading the plan

The plan is in the CI run of every PR (job `terraform`) and again in the
deploy run. Read it before merging. The CI plan and the deploy plan should
match.

**Stop, and do not merge, if the plan shows:**

- anything to **destroy** or **replace** (`-/+`, `must be replaced`). The
  deploy role cannot delete the data table, the buckets or the user pool
  anyway, so such an apply fails halfway. For the table and the media
  bucket the plan itself fails first (`Instance cannot be destroyed`:
  `prevent_destroy`).
- a change that turns off `deletion_protection_enabled` or
  `point_in_time_recovery` on the table, or a lifecycle rule on the media
  bucket that expires anything. Those are the ways a deploy could still
  lose data, and the guards above do not catch them.
- any `aws_ssm_parameter` or `aws_cognito_identity_provider` being
  created. Secrets are outside Terraform since 2026-10-31; one coming back
  would put its value into the state again.
- anything under `model/` in the admin web bucket (Terraform never owns it).

**Normal:**

- `aws_lambda_function.*` updated in place when its source changed, and
  only then: `make build` is reproducible, so the same source gives the
  same zip. The admin API and the Cognito trigger share one zip, so they
  change together. A new pip
  release or dependency version can change every zip once.
- `aws_s3_object.web[...]` / `aws_s3_object.site[...]` for the files the PR
  touched.

## Post-deploy checks

On a phone with the installed app, signed in as an admin, unless a step
says otherwise:

1. The Actions run is green, and the apply summary has the same numbers as
   the plan.
2. **Telegram:** send the bot a photo. It answers "Got it!", and the photo
   shows up in the Queue within a minute (process Lambda).
3. **Queue:** the model strip ends at "knows N cats from M photos". Label
   one session. The toast says what the model had guessed.
4. **Capture, as a collaborator:** start an encounter, take a photo of a
   known cat, Done. "Who did you meet?" shows three cats within a few
   seconds. Answer it.
5. **Stats:** "Uploads that never arrived" reads 0. Stats → Recognition
   model shows the session from step 3.
6. **Landing page**, if it changed: the public URL shows the new version
   (`terraform -chdir=infra/main output site_url`).

If a model or photo fetch fails, check the media bucket's CORS rule first
(`s3.tf`).

## Rollback

```bash
git revert -m 1 <merge-commit>     # on a branch, then a PR like any other
```

Merge the PR and the pipeline deploys the previous state. There is no
second path. What a revert does not undo:

- **Data.** Items and photos written by the newer code stay. Every change so
  far has been additive (new item types, new GSI2 entries), so the older
  code ignores them. Say in the PR if a change is not.
- **The model** under `model/` in the admin web bucket, which Terraform does
  not own. The older app simply doesn't load it.
- **Browser state.** IndexedDB stores stay at the version the newer app
  opened. Say in the PR if a change bumps a store and the old code cannot
  read it.

## The three things the pipeline does not do

All are owner-only, with an IAM Identity Center admin session
(`aws sso login --profile bgucats-prod-admin`, see `docs/codespaces.md`).

**Publishing the recognition model.** The export needs torch, which has no
place in CI, and a new model is rare. The export needs the research
environment, never the root one:

```bash
python -m venv ~/.venvs/research && . ~/.venvs/research/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install timm==1.0.30 onnx==1.23.2 onnxruntime==1.31.1 onnxscript==0.7.2 Pillow numpy
make model-export
deactivate
make model-publish PROFILE=bgucats-prod-admin
```

It prints the manifest and "a device downloads about 39.7 MB". Publish the
model before merging the code that loads it: nothing reads `model/` until
then, and the manifest is written last.

**`infra/bootstrap`** (the state backend and the GitHub roles). It cannot be
deployed by the role it creates. `infra/README.md` has the commands.

**Secrets.** The bot token, the webhook secret, the submitter salt (SSM
Parameter Store) and the Google OAuth client (Cognito's Google provider)
are set in AWS by `infra/scripts/set-secret.sh`, never by Terraform.
Anything Terraform manages is copied into its state, and the CI role reads
the state to plan, so any PR's workflow could read it. Until 2026-10-31
they came from `production` environment secrets; those GitHub secrets are
no longer used.

```bash
aws sso login --profile bgucats-prod-admin --use-device-code
AWS_PROFILE=bgucats-prod-admin infra/scripts/set-secret.sh telegram-bot-token
aws sso logout
```

The names: `telegram-bot-token` (paste from @BotFather after `/revoke`),
`telegram-webhook-secret` (generated), `google-oauth` (paste the client ID
and secret), `submitter-hash-salt` (new accounts only: it never replaces an
existing salt, because that would give every Telegram contributor a new
identity). The Telegram ones register the webhook themselves, at the API's
address, and stop if Telegram refuses it. **Revoking a token also drops the
bot's webhook**: on 2026-10-31 the first version of the script asked
Telegram for the old address, found none, and the bot went silent until
the webhook was set by hand. The ingest Lambda re-reads its secrets every 5
minutes, so a Telegram rotation can fail a few webhook calls for up to 5
minutes; Telegram retries them. Do it when the bot is quiet, and send the
bot `/start` afterwards.

In a **new account**, run `google-oauth` after the first deploy has created
the user pool and failed at the app client (which names the Google
provider), then deploy again; and `submitter-hash-salt` and both Telegram
ones (the second one registers the webhook).

## History

Notes from the hand-run deploys of 2026-10-29, kept for what they explain
about the code. Their `make tf-apply` and `git checkout` steps are
historical: today the same change would be a PR.

### Follow-up: uploads that never arrived (2026-10-29)

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


### Fix: Capture uploads stalled, and the model could not write (2026-10-29)

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


### The model's guess in plain sight, and guesses that never recorded (2026-10-29)

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


### "Who did you meet?" after each encounter, and uploads that keep going (2026-10-29)

**Asked for:** collaborators should see the model's guess for every
encounter and say which cat it was. The design should be good enough for
the early version of the real app. Uploads must not slow down, and should
keep going when the phone is locked or the app is closed, if a PWA can do
that.

**What changes:**

- **Capture's result screen.** "Done" opens "Who did you meet?" instead of
  closing the encounter. It shows the photos with their upload state and
  asks "Is it one of these?" over the model's three. The other choices are
  "Another cat…" (every cat, the model's order first, with a filter), "A cat
  that isn't here", "Not sure", "Take more photos" and "Skip". After an
  answer: "You said X · Encounter #N with this cat", whether the model
  agreed, then "Next cat" (straight into a new encounter) or "Finish".
  Admins get the same screen with similarity scores. The ranking is
  computed in the background while shooting and kept with the encounter, so
  a reload returns to the result screen.
- **Guesses are on by default.** The model downloads in the background from
  the first Capture visit. Only a data-saver phone is asked first.
- **Your recent encounters** shows "you: X ✓/✗" and "model: Y ✓/✗" against
  the label (`GET /api/encounters` adds `modelCatId` and `modelCatName` to
  `pick`).
- **Uploads:** three at a time. The screen is kept awake while files wait
  (Wake Lock). **Background Sync** (Chrome on Android): the outbox registers
  it with every photo and when the app is hidden, and sw.js uploads the
  queue with the app closed. The tokens are copied to IndexedDB
  `bgucats-auth` for it. Capture says which of these applies ("You can leave
  the app…" or "Keep the app open…").

**The iPhone limit, stated plainly:** Safari has no Background Sync or
background upload API, and suspends a hidden web app within seconds. On an
iPhone, uploads move only while the app is open on screen. The app keeps the
screen from locking while files wait, and tells the person to keep it open.
A native app would be the only way past this.

**Verified, headless (live Lambda GETs as a collaborator, stub writes):**
- 4 photos of one cat, then Done: "Is it one of these?" was up within a
  second, #1 was right, and the answer recorded "Encounter #7 · The model
  thought so too ✓".
- "Another cat…" listed all 22 cats, and the filter worked. A reload on the
  result screen came back to it with the guess.
- Offline, the guess still came (the model is cached).
- In full Chromium, 3 photos taken offline uploaded through the service
  worker 1 s after the signal came back, with no page open. Chrome's
  stripped-down headless shell never fires Background Sync, so a test there
  proves nothing.

**Expected plan:** code updates to `aws_lambda_function.admin`,
`.admin_presignup` (plus zip noise), and `aws_s3_object.web["app.js"]`,
`["capture.js"]`, `["outbox.js"]`, `["sw.js"]`, `["styles.css"]`,
`["recognition.js"]` if changed.
